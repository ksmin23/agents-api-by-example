"""Docker provider plumbing, OTLP transport and durable generic state storage.

No Docker socket is mounted into agent compute. Only resources bearing this
run's exact label may be removed. Source modules never contain API credentials.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
import io
import tarfile
import importlib.util
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import tempfile
import time
from uuid import uuid4

from .common import project_root, safe_error

LABEL = "io.agents-tutorial.run-id"
WORKER_IMAGE = "agents-tutorial-worker:0.1.0"
REGISTRY_IMAGE = "agents-tutorial-packages:0.1.0"
EXECUTOR_IMAGE = "agents-tutorial-executor:0.1.0"
COLLECTOR_IMAGE = "otel/opentelemetry-collector-contrib:0.164.0"
SKILL_COMMAND = [
    "/opt/venv/bin/python",
    "/opt/capabilities/skills/corporate-csv/scripts/run_report.py",
    "--input",
    "/workspace/sales.csv",
    "--output-dir",
    "/workspace/outputs",
]


def prepare(root=None):
    root = Path(root or project_root())
    spec = importlib.util.spec_from_file_location("tutorial_prepare", root / "deploy/prepare.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.prepare(root)


def docker(args, *, check=True, input=None, timeout=120):
    env = dict(os.environ)
    helper = "/Applications/Docker.app/Contents/Resources/bin"
    if Path(helper).is_dir():
        env["PATH"] = helper + os.pathsep + env.get("PATH", "")
    result = subprocess.run(
        ["docker", *map(str, args)],
        input=input,
        text=not isinstance(input, bytes),
        capture_output=True,
        timeout=timeout,
        env=env,
    )
    if check and result.returncode:
        # Keep raw engine errors out of notebooks; they can contain paths or environment data.
        raise RuntimeError(f"docker_{args[0]}_failed_exit_{result.returncode}")
    return result


def build_images(root=None, *, executor=False):
    root = Path(root or project_root())
    prepare(root)
    targets = [("worker", WORKER_IMAGE), ("packages", REGISTRY_IMAGE)]
    if executor:
        targets.append(("executor", EXECUTOR_IMAGE))
    out = root / "outputs/deployment-build"
    out.mkdir(parents=True, exist_ok=True)
    for target, tag in targets:
        result = docker(
            ["build", "--target", target, "-t", tag, root / "deploy"], check=False, timeout=600
        )
        (out / f"{target}.log").write_text(result.stdout + result.stderr)
        if result.returncode:
            raise RuntimeError(f"docker_build_{target}_failed; inspect outputs/deployment-build")
    return {
        target: docker(["image", "inspect", tag, "--format", "{{.Id}}"]).stdout.strip()
        for target, tag in targets
    }


class DockerLab:
    def __init__(self, chapter, root=None):
        self.root = Path(root or project_root())
        self.chapter = chapter
        self.run_id = uuid4().hex
        self.output_dir = self.root / "outputs/deployment" / chapter / self.run_id
        self.output_dir.mkdir(parents=True)
        self.containers = {}
        self.networks = {}
        self.checks = {}
        self.cleanup_errors = []
        self.failure = None
        self.started = time.monotonic()
        self.save()

    def manifest(self):
        return {
            "chapter": self.chapter,
            "run_id": self.run_id,
            "mode": "local_docker",
            "containers": self.containers,
            "networks": self.networks,
            "checks": self.checks,
            "cleanup_errors": self.cleanup_errors,
            "failure": self.failure,
            "elapsed_seconds": round(time.monotonic() - self.started, 3),
        }

    def save(self):
        (self.output_dir / "state.json").write_text(
            json.dumps(self.manifest(), ensure_ascii=False, indent=2)
        )

    def __enter__(self):
        return self

    def record(self, **checks):
        self.checks.update(checks)
        self.save()

    def network(self):
        name = f"aat-{self.run_id[:12]}-private"
        # The recovery scan below handles a lost CLI reply after resource creation.
        identifier = docker(
            ["network", "create", "--internal", "--label", f"{LABEL}={self.run_id}", name]
        ).stdout.strip()
        self.networks[identifier] = {"name": name, "removed": False}
        self.save()
        return identifier

    def create(self, role, image=WORKER_IMAGE, *, network=None, arguments=(), command=()):
        name = f"aat-{self.run_id[:12]}-{role}"
        args = [
            "create",
            "--name",
            name,
            "--label",
            f"{LABEL}={self.run_id}",
            "--memory",
            "512m",
            "--cpus",
            "1",
            "--pids-limit",
            "128",
            "--cap-drop",
            "ALL",
            "--security-opt",
            "no-new-privileges",
        ]
        if network:
            args += ["--network", network]
        identifier = docker([*args, *arguments, image, *command]).stdout.strip()
        self.containers[identifier] = {"role": role, "name": name, "removed": False}
        self.save()  # Persist ID before starting code.
        return identifier

    def start(self, identifier):
        self.assert_owned(identifier)
        docker(["start", identifier])

    def assert_owned(self, identifier, *, network=False):
        args = ["network", "inspect", identifier] if network else ["inspect", identifier]
        value = json.loads(docker(args).stdout)[0]
        labels = value.get("Labels", {}) if network else value["Config"].get("Labels", {})
        if labels.get(LABEL) != self.run_id:
            raise PermissionError("foreign_resource")
        return value

    def execute(self, identifier, args, **kwargs):
        self.assert_owned(identifier)
        return docker(["exec", identifier, *args], **kwargs)

    def copy_out(self, identifier, source, destination, *, check=True):
        self.assert_owned(identifier)
        destination = Path(destination)
        destination.parent.mkdir(parents=True, exist_ok=True)
        return docker(["cp", f"{identifier}:{source}", destination], check=check)

    def package_environment(self):
        network = self.network()
        registry = self.create(
            "packages", REGISTRY_IMAGE, network=network, arguments=["--network-alias", "packages"]
        )
        worker = self.create("worker", network=network)
        self.start(registry)
        self.start(worker)
        deadline = time.monotonic() + 25
        while True:
            probe = self.execute(
                worker,
                [
                    "python",
                    "-c",
                    "import urllib.request; urllib.request.urlopen('http://packages:8080/simple/acme-sales/',timeout=2).read()",
                ],
                check=False,
            )
            if probe.returncode == 0:
                break
            if time.monotonic() > deadline:
                raise TimeoutError("package_index_startup")
            time.sleep(0.2)
        return network, worker

    def install(self, worker, *, invalid_hash=False):
        lock = (
            "/opt/install/requirements.bad.txt" if invalid_hash else "/opt/install/requirements.txt"
        )
        return self.execute(
            worker,
            [
                "python",
                "-m",
                "pip",
                "install",
                "--index-url",
                "http://packages:8080/simple",
                "--trusted-host",
                "packages",
                "--no-deps",
                "--only-binary=:all:",
                "--require-hashes",
                "-r",
                lock,
            ],
            check=not invalid_hash,
        )

    def collect_report(self, worker, *, output_dir=None):
        """Copy each report file once into a caller-selected directory."""
        out = Path(output_dir) if output_dir is not None else self.output_dir / "downloaded"
        out.mkdir(parents=True, exist_ok=True)
        for name in ["summary.json", "report.md", "package_evidence.json"]:
            self.copy_out(worker, f"/workspace/outputs/{name}", out / name)
        metrics = json.loads((out / "summary.json").read_text())
        evidence = json.loads((out / "package_evidence.json").read_text())
        return metrics, evidence

    def cleanup(self):
        # Recover only exact run labels; never prune or remove all Docker objects.
        try:
            for identifier in docker(
                ["ps", "-aq", "--no-trunc", "--filter", f"label={LABEL}={self.run_id}"]
            ).stdout.split():
                self.containers.setdefault(identifier, {"removed": False, "recovered": True})
            for identifier in docker(
                ["network", "ls", "-q", "--filter", f"label={LABEL}={self.run_id}", "--no-trunc"]
            ).stdout.split():
                self.networks.setdefault(identifier, {"removed": False, "recovered": True})
        except Exception as error:
            self.cleanup_errors.append({"stage": "recover", **safe_error(error)})
        for network, resources in [(False, self.containers), (True, self.networks)]:
            for identifier, state in resources.items():
                try:
                    self.assert_owned(identifier, network=network)
                    docker(["network", "rm", identifier] if network else ["rm", "-f", identifier])
                    listing = (
                        ["network", "ls", "-q", "--filter", f"id={identifier}"]
                        if network
                        else ["ps", "-aq", "--filter", f"id={identifier}"]
                    )
                    if docker(listing).stdout.strip():
                        raise RuntimeError("resource_still_present")
                    state["removed"] = True
                except Exception as error:
                    self.cleanup_errors.append({"resource_id": identifier, **safe_error(error)})

    def __exit__(self, kind, error, traceback):
        if error:
            self.failure = safe_error(error)
        self.cleanup()
        self.save()
        summary = self.manifest()
        summary["status"] = "passed" if not self.failure and not self.cleanup_errors else "failed"
        for target in [self.output_dir / "summary.json", self.output_dir.parent / "latest.json"]:
            target.write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        if self.cleanup_errors:
            raise RuntimeError("docker_cleanup_incomplete; inspect local state.json")
        return False


@contextmanager
def prepare_executor(*, environment_id, remote_url, key, root=None):
    """Prepare Docker resources; the caller subscribes before starting the executor.

    This helper makes no Agents API calls and never starts the executor itself.
    The context also reclaims partially prepared Docker resources and key files.
    """
    root = Path(root or project_root())
    with ExitStack() as resources:
        provider = resources.enter_context(DockerLab("12_executor_compute", root))
        network, _ = provider.package_environment()
        secret = resources.enter_context(
            executor_secret(key, directory=root / "outputs" / ".executor-secrets")
        )
        executor = provider.create(
            "executor", EXECUTOR_IMAGE, network="bridge",
            arguments=[
                "--env", "ENVIRONMENT_ID=" + environment_id,
                "--env", "REMOTE_URL=" + remote_url,
                "--mount", f"type=bind,source={secret},target=/run/secrets/executor_key,readonly",
            ],
        )
        docker(["network", "connect", network, executor])
        yield provider, executor


def inspect_executor(provider, executor, *, expected_environment_id):
    """Capture selected Docker fields before cleanup, without printing credentials."""
    info = provider.assert_owned(executor)
    environment = dict(value.split("=", 1) for value in info["Config"].get("Env", []) if "=" in value)
    if environment.get("ENVIRONMENT_ID") != expected_environment_id:
        raise RuntimeError("Docker container is bound to a different environment")
    return {
        "environment_id": expected_environment_id,
        "container_environment_id": environment["ENVIRONMENT_ID"],
        "container_id": info["Id"],
        "container_name": info["Name"].lstrip("/"),
        "container_image": info["Config"]["Image"],
        "container_hostname": info["Config"]["Hostname"],
        "docker_state_file": str(provider.output_dir / "state.json"),
    }


class ApplicationHooks:
    """Caller-owned callbacks, not Codex native SessionStart hooks."""

    ALLOWED = {
        "chapter",
        "run_id",
        "session_id",
        "turn_id",
        "status",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "total_tokens",
    }

    def __init__(self, endpoint, run_id):
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import SimpleSpanProcessor

        self.provider = TracerProvider(
            resource=Resource({"service.name": "tutorial.application-hooks"})
        )
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter

            exporter = OTLPSpanExporter(endpoint=endpoint, timeout=5)
        else:
            from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

            exporter = InMemorySpanExporter()
        self.exporter = exporter
        self.provider.add_span_processor(SimpleSpanProcessor(exporter))
        self.closed = False
        self.tracer = self.provider.get_tracer("tutorial.deployment")
        self.run_id = run_id
        self.records = []

    def emit(self, event_name, **metadata):
        if self.closed:
            raise RuntimeError("Application telemetry is closed")
        if event_name not in {
            "report.started",
            "report.completed",
            "report.failed",
            "session.created",
            "turn.completed",
            "turn.failed",
        }:
            raise ValueError("unsupported_application_hook")
        attrs = {k: v for k, v in metadata.items() if k in self.ALLOWED and v is not None}
        attrs["run_id"] = self.run_id
        with self.tracer.start_as_current_span(
            event_name, attributes=attrs, record_exception=False, set_status_on_exception=False
        ):
            pass
        self.records.append({"event": event_name, **attrs})

    def flush(self):
        if not self.closed and not self.provider.force_flush(timeout_millis=5000):
            raise RuntimeError("Application telemetry flush incomplete")

    def close(self):
        if not self.closed:
            try:
                self.flush()
            finally:
                self.provider.shutdown()
                self.closed = True


def decode_otlp_spans(text):
    """Normalize app span fields from Collector JSONL; no API calls or recording."""
    def attributes(values):
        result = {}
        for field in values:
            value = field["value"]
            if "intValue" in value:
                result[field["key"]] = int(value["intValue"])
            else:
                result[field["key"]] = next(iter(value.values()), None)
        return result
    spans = []
    for line in text.splitlines():
        if not line.strip():
            continue
        for resource in json.loads(line).get("resourceSpans", []):
            service = attributes(resource.get("resource", {}).get("attributes", [])).get("service.name")
            for scope in resource.get("scopeSpans", []):
                for span in scope.get("spans", []):
                    spans.append(dict(name=span["name"], trace_id=span.get("traceId"),
                        span_id=span.get("spanId"), service_name=service,
                        attributes=attributes(span.get("attributes", []))))
    return spans


def start_collector(lab, network):
    identifier = lab.create(
        "collector",
        COLLECTOR_IMAGE,
        network="bridge",
        arguments=[
            "--user",
            "10001:10001",
            "--publish",
            "127.0.0.1::4318",
            "--mount",
            f'type=bind,source={lab.root / "deploy/otel-collector.yaml"},target=/etc/tutorial.yaml,readonly',
        ],
        command=["--config=/etc/tutorial.yaml"],
    )
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode="w") as stream:
        directory = tarfile.TarInfo("evidence")
        directory.type = tarfile.DIRTYPE
        directory.mode, directory.uid, directory.gid = 0o700, 10001, 10001
        stream.addfile(directory)
    docker(["cp", "--archive", "-", f"{identifier}:/"], input=archive.getvalue())
    docker(["network", "connect", "--alias", "collector", network, identifier])
    lab.start(identifier)
    endpoint = "http://" + docker(["port", identifier, "4318/tcp"]).stdout.strip()
    import urllib.request

    for _ in range(60):
        try:
            req = urllib.request.Request(
                endpoint + "/v1/traces", data=b"{}", headers={"Content-Type": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=1) as response:
                if response.status == 200:
                    return identifier, endpoint
        except OSError:
            time.sleep(0.2)
    (lab.output_dir / "collector-startup.log").write_text(
        docker(["logs", identifier], check=False).stdout
        + docker(["logs", identifier], check=False).stderr
    )
    raise TimeoutError("collector_startup")


def read_collector_file(lab, collector, filename, *, needle=None):
    destination = lab.output_dir / "telemetry" / filename
    for _ in range(30):
        result = lab.copy_out(collector, "/evidence/" + filename, destination, check=False)
        if result.returncode == 0 and destination.stat().st_size:
            text = destination.read_text()
            if needle is None or needle in text:
                return text
        time.sleep(0.2)
    raise TimeoutError("collector_file_not_ready")


class JobStore:
    """One provisioning owner per job. An unknown result requires reconciliation."""

    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.path) as db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS jobs (job_id TEXT PRIMARY KEY, owner TEXT NOT NULL, state TEXT NOT NULL, resource_id TEXT)"
            )

    def claim(self, job_id, owner):
        with sqlite3.connect(self.path, timeout=10) as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT owner,state,resource_id FROM jobs WHERE job_id=?", (job_id,)
            ).fetchone()
            if row:
                if row[0] != owner:
                    raise PermissionError("foreign_job")
                return {"created": False, "state": row[1], "resource_id": row[2]}
            db.execute("INSERT INTO jobs VALUES (?,?,?,NULL)", (job_id, owner, "provisioning"))
            return {"created": True, "state": "provisioning", "resource_id": None}

    def transition(self, job_id, owner, expected, state, resource_id=None):
        if state not in {"running", "needs_reconciliation", "completed", "cleaned"}:
            raise ValueError("invalid_state")
        with sqlite3.connect(self.path) as db:
            changed = db.execute(
                "UPDATE jobs SET state=?,resource_id=COALESCE(?,resource_id) WHERE job_id=? AND owner=? AND state=?",
                (state, resource_id, job_id, owner, expected),
            ).rowcount
            if changed != 1:
                raise RuntimeError("concurrent_state_change")


def usage_summary(usage):
    if usage is None:
        return {
            "reported": False,
            "input_tokens": None,
            "output_tokens": None,
            "total_tokens": None,
        }
    if hasattr(usage, "model_dump"):
        usage = usage.model_dump()
    return {
        "reported": True,
        **{k: usage.get(k) for k in ["input_tokens", "output_tokens", "total_tokens"]},
    }


def executor_key(root):
    from dotenv import dotenv_values

    return os.environ.get("OPENAI_EXECUTOR_API_KEY") or dotenv_values(
        Path(root) / ".env.local"
    ).get("OPENAI_EXECUTOR_API_KEY")


@contextmanager
def executor_secret(key, *, directory=None):
    """Create one protected mount file in a caller-selected shared directory.

    Docker Desktop may not see system temporary directories. The notebook passes
    a Git-ignored project directory shared with the Docker engine. No key enters
    image layers, Docker configuration environment variables, or command argv.
    """
    if directory is not None:
        directory = Path(directory).resolve()
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix="tutorial-executor-key-", dir=directory) as temporary:
        secret = Path(temporary) / "executor_key"
        secret.write_text(key)
        secret.chmod(0o444)  # Parent directory is 0700. Mounted read-only.
        yield secret
