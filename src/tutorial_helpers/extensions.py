"""Generic bundle/cache/approval-input utilities; no API schemas or execution loop."""

from __future__ import annotations
import hashlib, io, json, shutil, zipfile
from dataclasses import dataclass
from pathlib import Path


class PolicyError(ValueError):
    """A safe error code that may be returned to the agent."""


def read_skill_metadata(folder):
    """Read this tutorial's plain one-line name/description header, not general YAML."""
    lines = (Path(folder) / "SKILL.md").read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != "---" or "---" not in lines[1:]:
        raise ValueError("Skill manifest must start with a delimited header")
    fields = {}
    for line in lines[1:lines.index("---", 1)]:
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition(":")
        value = value.strip()
        if (not separator or key not in {"name", "description"} or key in fields
            or not value or value[0] in "|>\"'[]{}&*!" or " #" in value):
            raise ValueError("Use unquoted one-line name and description fields for this tutorial")
        fields[key] = value
    if set(fields) != {"name", "description"}:
        raise ValueError("Skill name and description are required")
    return fields


def archive_folder(folder):
    folder = Path(folder)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(folder.rglob("*")):
            if "__pycache__" in path.parts or path.suffix == ".pyc":
                continue
            if path.is_symlink():
                raise ValueError("Do not package symlinks")
            if not path.is_file():
                continue
            if path.suffix not in {".py", ".md", ".json"}:
                raise ValueError("Unexpected bundle file type")
            name = (Path(folder.name) / path.relative_to(folder)).as_posix()
            info = zipfile.ZipInfo(name, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100644 << 16
            archive.writestr(info, path.read_bytes())
    return buffer.getvalue()


def sync_plugin(root):
    root = Path(root)
    target = root / "plugins/sales-reporting"
    shutil.copytree(
        root / "skills/csv-report",
        target / "skills/csv-report",
        dirs_exist_ok=True,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    (target / "servers").mkdir(exist_ok=True)
    (target / "assets").mkdir(exist_ok=True)
    shutil.copyfile(
        root / "examples/mcp/sales_targets_server.py", target / "servers/sales_targets_server.py"
    )
    shutil.copyfile(root / "data/sales_targets.json", target / "assets/sales_targets.json")
    return target


@dataclass(frozen=True)
class Approval:
    approved: bool
    report_id: str
    sha256: str
    channel: str
    actor: str
    origin: str


def interactive_approval(report_id, digest, channel):
    print("Action required: review the downloaded report before deciding.", flush=True)
    print("VS Code: use the input box at the top of the window.", flush=True)
    print("Jupyter/Colab: use the notebook's input prompt.", flush=True)
    print("Type APPROVE to register, or REJECT to decline, then press Enter.", flush=True)
    print("The cell stays busy until you reply; input has no automatic timeout.", flush=True)
    entered = input(
        f"Register {report_id} in local training storage? SHA256={digest}. Type APPROVE: "
    )
    return Approval(
        entered == "APPROVE", report_id, digest, channel, "local-learner", "interactive"
    )


def validation_approval(report_id, digest, channel):
    # Explicit deterministic test input, never described as a real human decision.
    return Approval(True, report_id, digest, channel, "validation-fixture", "fixture")


class ResultCache:
    """Generic JSON request/result storage; the caller constructs and sends results.

    This is a single-responder tutorial cache, not distributed exactly-once
    execution. Unknown side-effect outcomes require reconciliation by the caller.
    """

    def __init__(self, directory):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, identity):
        return self.directory / (
            hashlib.sha256(json.dumps(identity).encode()).hexdigest() + ".json"
        )

    def load(self, identity, request):
        path = self._path(identity)
        if not path.exists():
            return None
        saved = json.loads(path.read_text())
        if saved["request"] != request:
            raise ValueError("call_identity_changed")
        return saved["result"]

    def save(self, identity, request, result):
        path = self._path(identity)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(
                {"identity": identity, "request": request, "result": result},
                ensure_ascii=False,
                indent=2,
            )
        )
        temporary.replace(path)
