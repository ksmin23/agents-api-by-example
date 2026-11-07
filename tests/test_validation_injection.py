"""Source stays readable; stronger checks in execution copies cannot bypass cleanup."""

import ast
import copy
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock
import nbformat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from notebook_validation import instrument_notebook
from tutorial_helpers.common import Settings, safe_error
from tutorial_helpers.validation import save_validation, validate_lesson


class ValidationCopyTests(unittest.TestCase):
    def sample(self, body="value = 42", cleanup="pass"):
        return nbformat.v4.new_notebook(
            cells=[
                nbformat.v4.new_code_cell(
                    f"try:\n    {body}\nfinally:\n    cleanup_errors = cleanup_resources(client, sessions, agents, attempts)\n    {cleanup}\n",
                    metadata={"tags": ["requires_api"]},
                )
            ]
        )

    def execute(self, notebook, namespace):
        setup, workflow = notebook.cells
        exec(setup.source, namespace)
        namespace.update(_validate_lesson=self.validator)
        exec(workflow.source, namespace)

    def namespace(self, directory, cleanup):
        client = Mock()
        client.beta.agents.sessions.items.list.return_value = []
        return {
            "client": client,
            "sessions": {"s": {}},
            "agents": {},
            "attempts": [],
            "output_dir": Path(directory) / "run",
            "run_id": "fixture",
            "settings": Settings(True, "fixture", Path(directory), "fixture-key"),
            "cleanup_resources": cleanup,
        }

    def test_original_notebook_is_unchanged(self):
        source = self.sample()
        before = nbformat.writes(source)
        copied = copy.deepcopy(source)
        instrument_notebook(copied, "02_first_agent", live=True)
        self.assertEqual(nbformat.writes(source), before)
        self.assertEqual(len(copied.cells), len(source.cells) + 1)
        self.assertIn("validation_only", copied.cells[0].metadata.tags)

    def test_offline_execution_does_not_inject_or_contact_api(self):
        nb = self.sample()
        before = nbformat.writes(nb)
        instrument_notebook(nb, "02_first_agent")
        self.assertEqual(nbformat.writes(nb), before)

    def test_validation_failure_propagates_after_cleanup_and_failed_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            cleanup = Mock(return_value=[])
            env = self.namespace(temp, cleanup)
            self.validator = Mock(side_effect=ValueError("wrong answer"))
            nb = self.sample()
            instrument_notebook(nb, "02_first_agent", live=True)
            with self.assertRaises(ValueError):
                self.execute(nb, env)
            cleanup.assert_called_once()
            receipt = json.loads((env["output_dir"] / "summary.json").read_text())
            self.assertEqual(receipt["status"], "failed")
            self.assertEqual(receipt["failure"]["exception"], "ValueError")

    def test_api_failure_cleans_up_without_claiming_validation_ran(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self.namespace(temp, Mock(return_value=[]))
            self.validator = Mock()
            nb = self.sample("raise TimeoutError('fixture')")
            instrument_notebook(nb, "02_first_agent", live=True)
            with self.assertRaises(TimeoutError):
                self.execute(nb, env)
            self.validator.assert_not_called()
            env["cleanup_resources"].assert_called_once()
            self.assertEqual(env["_validation_summary"]["status"], "failed")
            self.assertEqual(env["_validation_summary"]["checks"], {})

    def test_cleanup_failure_cannot_produce_passed_receipt(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self.namespace(temp, Mock(return_value=[{"session_id": "s"}]))
            self.validator = Mock(return_value=({"checked": True}, []))
            nb = self.sample(cleanup="if cleanup_errors: raise RuntimeError('cleanup')")
            instrument_notebook(nb, "02_first_agent", live=True)
            with self.assertRaises(RuntimeError):
                self.execute(nb, env)
            self.assertEqual(env["_validation_summary"]["status"], "failed")
            self.assertTrue(env["_validation_summary"]["cleanup_errors"])

    def test_history_is_read_before_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            calls = []
            env = self.namespace(temp, lambda *args: calls.append("cleanup") or [])
            env["client"].beta.agents.sessions.items.list.side_effect = (
                lambda *a, **k: calls.append("history") or []
            )
            self.validator = lambda *args: (calls.append("validate") or {}, [])
            nb = self.sample()
            instrument_notebook(nb, "02_first_agent", live=True)
            self.execute(nb, env)
            self.assertEqual(calls, ["history", "validate", "cleanup"])

    def test_wrong_csv_result_is_rejected_by_real_validator_after_source_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self.namespace(temp, Mock(return_value=[]))
            env["settings"] = Settings(True, "fixture", ROOT, "fixture-key")
            turn = SimpleNamespace(id="t", status="completed", usage=None)
            env["result"] = SimpleNamespace(
                turn=turn, turn_id="t", session_id="s", output_text=json.dumps({"total_revenue": 0})
            )
            env["client"].beta.agents.sessions.items.list.return_value = [
                SimpleNamespace(
                    type="command_execution", turn_id="t", status="completed", exit_code=0
                )
            ]
            self.validator = validate_lesson
            nb = self.sample()
            instrument_notebook(nb, "02_first_agent", live=True)
            with self.assertRaises(ValueError):
                self.execute(nb, env)
            env["cleanup_resources"].assert_called_once()
            self.assertEqual(env["_validation_summary"]["status"], "failed")

    def test_observability_without_docker_does_not_require_a_transport(self):
        with tempfile.TemporaryDirectory() as temp:
            env = self.namespace(temp, Mock(return_value=[]))
            env["docker_enabled"] = False
            self.validator = Mock(return_value=({"checked": True}, []))
            nb = self.sample()
            instrument_notebook(nb, "13_hooks_telemetry", live=True)
            self.execute(nb, env)
            self.assertEqual(env["_validation_summary"]["status"], "passed")

    def test_no_validation_helpers_or_oracles_in_source_notebooks(self):
        forbidden = {
            "verify_metrics",
            "verify_report",
            "verify_enriched",
            "verify_tool_execution",
            "verify_execution",
            "save_validation",
            "analyze_csv",
            "daily_revenue",
            "render_markdown",
            "checks",
        }
        for path in (ROOT / "notebooks").rglob("*.ipynb"):
            if ".ipynb_checkpoints" in path.parts:
                continue
            notebook = nbformat.read(path, as_version=4)
            for cell in notebook.cells:
                if cell.cell_type != "code":
                    continue
                for node in ast.walk(ast.parse(cell.source)):
                    if isinstance(node, ast.Name):
                        self.assertNotIn(node.id, forbidden, str(path))
            self.assertFalse(
                any("validation_only" in c.metadata.get("tags", []) for c in notebook.cells)
            )

    def test_wrong_docker_result_is_rejected_before_success_record_and_context_closes(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            (directory / "downloaded").mkdir()
            (directory / "downloaded/summary.json").write_text('{"total_revenue": 0}')
            lab = Mock(root=ROOT, output_dir=directory)
            manager = Mock()
            manager.__enter__ = Mock(return_value=lab)
            manager.__exit__ = Mock(return_value=False)
            notebook = nbformat.v4.new_notebook(
                cells=[
                    nbformat.v4.new_code_cell(
                        "with DockerLab('12_self_hosted', root) as lab:\n    local_metrics, local_evidence = {}, {}"
                    )
                ]
            )
            instrument_notebook(notebook, "12_self_hosted", docker=True)
            with self.assertRaises(ValueError):
                exec(
                    notebook.cells[0].source,
                    {"DockerLab": Mock(return_value=manager), "root": ROOT},
                )
            manager.__exit__.assert_called_once()
            lab.record.assert_not_called()

    def test_private_package_validation_checks_identity_install_location_and_input_digest(self):
        import hashlib
        from tutorial_helpers.validation import verify_private_package

        content = b"fixture"
        evidence = {
            "distribution": "acme-sales",
            "version": "0.1.0",
            "module_file": "/opt/venv/lib/acme_sales/__init__.py",
            "input_sha256": hashlib.sha256(content).hexdigest(),
        }
        verify_private_package(evidence, content)
        for change in [
            {"version": "wrong"},
            {"module_file": "/tmp/forged.py"},
            {"input_sha256": "wrong"},
        ]:
            with self.subTest(change=change), self.assertRaises(ValueError):
                verify_private_package({**evidence, **change}, content)

    def test_all_api_lessons_have_one_instrumentable_cleanup_boundary(self):
        for path in (ROOT / "notebooks").rglob("*.ipynb"):
            if ".ipynb_checkpoints" in path.parts:
                continue
            nb = nbformat.read(path, as_version=4)
            if not any("api_preparation" in c.metadata.get("tags", []) for c in nb.cells):
                continue
            chapter = "preface" if path.name == "quickstart.ipynb" else path.stem
            instrument_notebook(nb, chapter, live=True)
            self.assertIn("validation_only", nb.cells[0].metadata.tags)


if __name__ == "__main__":
    unittest.main()
