"""Offline operational contracts. Live Docker notebooks are validated separately."""

from concurrent.futures import ThreadPoolExecutor
import importlib.util
import hashlib
import ast
import time
import contextlib
import io
from notebook_code import tree, cells
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from tutorial_helpers.deployment import (
    ApplicationHooks,
    DockerLab,
    JobStore,
    LABEL,
    prepare,
    usage_summary,
)

ROOT = Path(__file__).resolve().parents[1]


class JobTests(unittest.TestCase):
    def test_concurrent_claims_have_one_provisioning_winner(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "jobs.sqlite3"
            JobStore(path)

            def claim(_):
                return JobStore(path).claim("sales-job", "owner")["created"]

            with ThreadPoolExecutor(max_workers=8) as pool:
                self.assertEqual(sum(pool.map(claim, range(16))), 1)

    def test_foreign_owner_and_stale_transition_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            store = JobStore(Path(temp) / "jobs.sqlite3")
            store.claim("job", "owner")
            with self.assertRaises(PermissionError):
                store.claim("job", "other")
            store.transition("job", "owner", "provisioning", "running", "container-id")
            with self.assertRaises(RuntimeError):
                store.transition("job", "owner", "provisioning", "completed")
            store.transition("job", "owner", "running", "needs_reconciliation")
            self.assertEqual(
                store.claim("job", "owner")["state"], "needs_reconciliation"
            )


class TelemetryTests(unittest.TestCase):
    def test_usage_none_is_unknown_and_zero_is_valid(self):
        self.assertIsNone(usage_summary(None)["total_tokens"])
        self.assertEqual(usage_summary({"total_tokens": 0})["total_tokens"], 0)
        self.assertEqual(
            usage_summary(
                {
                    "input_tokens": 100,
                    "output_tokens": 20,
                    "total_tokens": 120,
                    "cached_tokens": 30,
                    "reasoning_tokens": 5,
                }
            )["total_tokens"],
            120,
        )

    def test_notebook_dispatch_excludes_prompt_and_subagent_spans(self):
        tree13 = tree(13)
        event_loop = next(
            n
            for n in ast.walk(tree13)
            if isinstance(n, ast.For)
            and isinstance(n.target, ast.Name)
            and n.target.id == "event"
            and isinstance(n.iter, ast.Name)
            and n.iter.id == "stream"
        )
        code = compile(
            ast.Module(body=event_loop.body, type_ignores=[]),
            "chapter-13-dispatch",
            "exec",
        )
        lab = SimpleNamespace(
            events=[], sessions={}, started=time.monotonic(), save=Mock()
        )
        hooks = SimpleNamespace(emit=Mock())
        env = {
            "sessions": {},
            "started": time.monotonic(),
            "hooks": hooks,
            "time": time,
            "check_event": __import__(
                "tutorial_helpers.common", fromlist=["check_event"]
            ).check_event,
        }
        for event in [
            SimpleNamespace(
                type="agent.session.turn.output_text.delta", delta="private prompt"
            ),
            SimpleNamespace(
                type="agent.session.turn.completed",
                turn=SimpleNamespace(subagent_id="sub"),
            ),
        ]:
            env["event"] = event
            with contextlib.redirect_stdout(io.StringIO()):
                exec(code, env)
        hooks.emit.assert_not_called()
        env["event"] = SimpleNamespace(
            type="agent.session.created",
            session=SimpleNamespace(
                id="sess_test", environment=SimpleNamespace(id="env_test")
            ),
        )
        with contextlib.redirect_stdout(io.StringIO()):
            exec(code, env)
        hooks.emit.assert_called_once_with(
            "session.created", chapter=13, session_id="sess_test"
        )
        env["event"] = SimpleNamespace(
            type="agent.session.turn.completed",
            session_id="sess_test",
            turn=SimpleNamespace(id="turn_test", subagent_id=None, status="completed"),
        )
        exec(code, env)
        hooks.emit.assert_called_with(
            "turn.completed",
            chapter=13,
            session_id="sess_test",
            turn_id="turn_test",
            status="completed",
        )

    def test_native_adapter_allowlists_metadata(self):
        spec = importlib.util.spec_from_file_location(
            "tutorial_hook", ROOT / "deploy/native_hooks/session_start.py"
        )
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        record = module.make_record(
            {
                "hook_event_name": "SessionStart",
                "session_id": "sess_test",
                "prompt": "private",
                "cwd": "private",
                "env": {"KEY": "private"},
            }
        )
        self.assertEqual(set(record), {"hook_event_name", "session_id", "source"})
        with self.assertRaises(ValueError):
            module.make_record({"hook_event_name": "Untrusted", "session_id": "s"})


class CleanupTests(unittest.TestCase):
    def test_foreign_container_is_never_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            lab = DockerLab("fixture", temp)
            fake = SimpleNamespace(
                stdout=json.dumps([{"Config": {"Labels": {LABEL: "foreign"}}}])
            )
            with patch(
                "tutorial_helpers.deployment.docker", return_value=fake
            ) as engine:
                with self.assertRaises(PermissionError):
                    lab.assert_owned("foreign")
                self.assertFalse(any("rm" in c.args[0] for c in engine.call_args_list))

    def test_one_cleanup_error_does_not_stop_other_owned_resources(self):
        with tempfile.TemporaryDirectory() as temp:
            lab = DockerLab("fixture", temp)
            lab.containers = {"bad": {"removed": False}, "good": {"removed": False}}

            def owned(identifier, **_):
                if identifier == "bad":
                    raise RuntimeError("provider_unavailable")

            with (
                patch.object(lab, "assert_owned", side_effect=owned),
                patch(
                    "tutorial_helpers.deployment.docker",
                    return_value=SimpleNamespace(stdout=""),
                ),
            ):
                lab.cleanup()
            self.assertTrue(lab.containers["good"]["removed"])
            self.assertFalse(lab.containers["bad"]["removed"])
            self.assertEqual(len(lab.cleanup_errors), 1)

    def preflight(self, key, app_key="app-key"):
        preparation = next(
            c for c in cells(12)
            if "api_preparation" in c.get("metadata", {}).get("tags", [])
        )
        prefix = ast.parse("".join(preparation["source"])).body
        get_key = Mock(return_value=key)
        env = {
            "settings": SimpleNamespace(enabled=True, api_key=app_key),
            "docker_enabled": True,
            "executor_key": get_key,
            "root": ROOT,
        }
        exec(
            compile(
                ast.Module(body=prefix, type_ignores=[]), "chapter-12-preflight", "exec"
            ),
            env,
        )

    def test_self_hosted_workflow_request_wiring_and_separate_cleanup_with_mocks(self):
        # This executes the notebook flow with mocked SDK/provider objects.
        # It is NOT a real API connection or exec-server dispatch verification.
        from contextlib import ExitStack
        from unittest.mock import MagicMock
        from uuid import uuid4
        from notebook_code import definition
        from tutorial_helpers.common import Settings, safe_error, new_session_metadata, delete_session_safely, cleanup_resources, cleanup_on_error, check_event
        from tutorial_helpers.validation import verify_metrics, save_validation
        from tutorial_helpers.extensions import ResultCache, PolicyError
        from tutorial_helpers.deployment import EXECUTOR_IMAGE, prepare_executor, inspect_executor
        from openai import ConflictError, NotFoundError
        import httpx2
        import tempfile
        import json

        data = {
            "row_count": 6,
            "total_quantity": 11,
            "total_revenue": 127500,
            "by_product": {"A": 30000, "B": 75000, "C": 22500},
        }
        with tempfile.TemporaryDirectory() as directory:
            client = Mock()
            session = SimpleNamespace(
                id="sess_fixture",
                environment=SimpleNamespace(
                    id="env_fixture",
                    remote_url="https://api.openai.com/executor-fixture",
                ),
                required_actions=[SimpleNamespace(type="environment_connection")],
            )
            deleted = False

            def create(**kwargs):
                session.metadata = kwargs["metadata"]
                return session

            def retrieve(*args, **kwargs):
                if deleted:
                    raise NotFoundError(
                        "fixture",
                        response=httpx2.Response(
                            404,
                            request=httpx2.Request(
                                "GET", "https://api.openai.com/v1/agents/fixture"
                            ),
                        ),
                        body=None,
                    )
                return SimpleNamespace(status="idle")

            def delete(*args, **kwargs):
                nonlocal deleted
                deleted = True
                return SimpleNamespace(deleted=True)

            api = client.beta.agents.sessions
            api.create.side_effect = create
            api.retrieve.side_effect = retrieve
            api.delete.side_effect = delete
            api.list.return_value = [session]
            turn = SimpleNamespace(id="turn_fixture", status="completed", usage=None, subagent_id=None)
            api.turns.retrieve.return_value = turn
            result = SimpleNamespace(
                session_id=session.id,
                turn_id=turn.id,
                turn=turn,
                output_text=json.dumps(data),
            )
            item = SimpleNamespace(
                type="command_execution",
                turn_id=turn.id,
                command="python run_report.py",
                status="completed",
                exit_code=0,
                output=json.dumps(data),
            )
            item.to_dict = lambda: {
                "turn_id": turn.id,
                "command": "python run_report.py",
                "status": "completed",
                "exit_code": 0,
                "output": json.dumps(data),
            }
            api.items.list.return_value = [item]
            events = [
                SimpleNamespace(type="agent.session.requires_action", session=session),
                SimpleNamespace(type="agent.session.turn.item.done", item=item),
            ]
            stream = MagicMock()
            stream.__iter__.return_value = iter(events)
            stream.get_final_result.return_value = result
            manager = MagicMock()
            manager.__enter__.return_value = stream
            api.stream.return_value.with_result_collection.return_value = manager
            connection_manager = MagicMock()
            connection_manager.__enter__.return_value = iter(
                [
                    SimpleNamespace(
                        type="agent.session.environment.connected",
                        environment=SimpleNamespace(id="env_fixture"),
                    )
                ]
            )
            api.events.stream.return_value = connection_manager
            connection_order = []
            connection_manager.__enter__.side_effect = lambda: (
                connection_order.append("subscribe") or iter([
                    SimpleNamespace(type="agent.session.environment.connected", environment=session.environment)
                ])
            )
            request = api.stream.return_value
            api.stream.side_effect = lambda *args, **kwargs: connection_order.append("submit") or request
            provider = MagicMock()
            provider.package_environment.return_value = (
                "network_fixture",
                "worker_fixture",
            )
            provider.create.return_value = "executor_fixture"
            provider.start.side_effect = lambda *args: connection_order.append("start")
            provider.output_dir = Path(directory) / "docker-output"
            provider.assert_owned = Mock()
            provider.assert_owned.return_value = {
                "Id": "executor_fixture",
                "Name": "/executor_fixture",
                "Config": {
                    "Env": ["ENVIRONMENT_ID=env_fixture", "CODEX_API_KEY=do-not-print-fixture"],
                    "Image": EXECUTOR_IMAGE,
                    "Hostname": "executor-fixture-host",
                },
            }
            provider.collect_report.return_value = (
                data,
                {"distribution": "acme-sales", "version": "0.1.0",
                 "module_file": "/opt/venv/lib/python3.12/site-packages/acme_sales/__init__.py"},
            )
            factory = MagicMock()
            factory.return_value.__enter__.return_value = provider
            env = {
                "settings": Settings(
                    True, "fixture", Path(directory), api_key="app-fixture-key"
                ),
                "root": Path(directory),
                "expected": data,
                "CHAPTER": "12_self_hosted",
                "csv_bytes": b"fixture-input",
                "hashlib": hashlib,
                "image_input_sha256": hashlib.sha256(b"fixture-input").hexdigest(),
                "docker_enabled": True,
                "executor_key": Mock(return_value="executor-fixture-key"),
                "new_session_metadata": new_session_metadata,
                "delete_session_safely": delete_session_safely,
                "cleanup_resources": cleanup_resources,
                "cleanup_on_error": cleanup_on_error,
                "sys": __import__("sys"),
                "save_validation": save_validation,
                "check_event": check_event,
                "verify_tool_execution": __import__("tutorial_helpers.validation", fromlist=["verify_tool_execution"]).verify_tool_execution,
                "ResultCache": ResultCache,
                "PolicyError": PolicyError,
                "OpenAI": Mock(return_value=client),
                "ExitStack": ExitStack,
                "DockerLab": factory,
                "prepare_executor": prepare_executor,
                "inspect_executor": inspect_executor,
                "EXECUTOR_IMAGE": EXECUTOR_IMAGE,
                "safe_error": safe_error,
                "verify_metrics": verify_metrics,
                "json": json,
                "time": time,
                "uuid4": uuid4,
                "NotFoundError": NotFoundError,
                "ConflictError": ConflictError,
                "docker": Mock(),
                "BASE_INSTRUCTIONS": "fixture",
                "METRICS_CONTRACT": "Return summary JSON",
            }
            # Execute the task definition from the notebook too, catching missing inputs.
            task = next(
                n
                for n in tree(12).body
                if isinstance(n, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "task" for t in n.targets)
            )
            exec(
                compile(
                    ast.Module(body=[task], type_ignores=[]), "chapter-12-task", "exec"
                ),
                env,
            )
            workflows = [c for c in cells(12) if any(
                t.startswith("self_hosted_step_") for t in c.get("metadata", {}).get("tags", [])
            )]
            preparation = next(
                c for c in cells(12)
                if "api_preparation" in c.get("metadata", {}).get("tags", [])
            )
            captured = io.StringIO()
            with (
                contextlib.redirect_stdout(captured),
                patch("openai.OpenAI", return_value=client),
                patch("tutorial_helpers.deployment.DockerLab", factory),
                patch("tutorial_helpers.deployment.docker", env["docker"]),
            ):
                exec("".join(preparation["source"]), env)
                state = next(c for c in cells(12) if c["id"] == "12-run-state")
                exec("".join(state["source"]), env)
                for workflow in workflows:
                    exec("".join(workflow["source"]), env)
            self.assertEqual(
                api.create.call_args.kwargs["environment"]["type"], "self_hosted"
            )
            args = provider.create.call_args.kwargs["arguments"]
            self.assertIn("ENVIRONMENT_ID=env_fixture", args)
            self.assertIn("REMOTE_URL=https://api.openai.com/executor-fixture", args)
            self.assertNotIn("executor-fixture-key", str(args))
            self.assertIn("corporate-csv", api.stream.call_args.kwargs["input"])
            factory.return_value.__exit__.assert_called_once()
            self.assertTrue(env["sessions"][session.id]["verified_absent"])
            self.assertFalse(env["cleanup_errors"])
            self.assertNotIn("summary", env)
            self.assertEqual(env["execution_context"]["container_environment_id"], "env_fixture")
            self.assertNotIn("executor-fixture-host", captured.getvalue())
            self.assertEqual(env["execution_context"]["container_hostname"], "executor-fixture-host")
            self.assertIn("Docker executor: executor_fixture", captured.getvalue())
            self.assertEqual(connection_order, ["subscribe", "start", "submit"])
            self.assertNotIn("do-not-print-fixture", captured.getvalue())
            self.assertIn("resources cleaned up", captured.getvalue())

    def test_executor_secret_uses_shared_directory_and_removes_file(self):
        import stat
        from tutorial_helpers.deployment import executor_secret

        with tempfile.TemporaryDirectory() as folder:
            shared = Path(folder) / "shared"
            with executor_secret("executor-fixture-only", directory=shared) as path:
                self.assertIn(shared.resolve(), path.parents)
                self.assertEqual(path.read_text(), "executor-fixture-only")
                self.assertEqual(stat.S_IMODE(path.parent.stat().st_mode), 0o700)
            self.assertFalse(path.exists())
            self.assertEqual(list(shared.iterdir()), [])

    def test_missing_executor_key_stops_before_api_or_compute(self):
        with self.assertRaisesRegex(RuntimeError, "dedicated_executor_key_required"):
            self.preflight(None)

    def test_application_key_cannot_be_reused_as_executor_key(self):
        with self.assertRaisesRegex(RuntimeError, "must_differ"):
            self.preflight("app-key")

    def test_offline_switch_does_not_read_executor_key_or_start_compute(self):
        cell = next(
            c
            for c in cells(12)
            if "api_preparation" in c.get("metadata", {}).get("tags", [])
        )
        key = Mock(side_effect=AssertionError("must not read key"))
        env = {"settings": SimpleNamespace(enabled=False), "executor_key": key}
        with self.assertRaisesRegex(RuntimeError, "RUN_LIVE=True"), contextlib.redirect_stdout(io.StringIO()):
            exec("".join(cell["source"]), env)
        key.assert_not_called()


if __name__ == "__main__":
    unittest.main()
