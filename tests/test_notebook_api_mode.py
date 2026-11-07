"""One explicit API preparation; native nbclient tags control offline execution."""

import ast
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_notebooks import validate_api_tags


class ApiModeTests(unittest.TestCase):
    def notebooks(self):
        return [
            (p, nbformat.read(p, as_version=4))
            for p in (ROOT / "notebooks").rglob("*.ipynb")
            if ".ipynb_checkpoints" not in p.parts
        ]

    def test_all_live_notebooks_have_exactly_one_preparation_and_no_repeated_mode_guards(self):
        live_count = 0
        for path, nb in self.notebooks():
            with self.subTest(notebook=path.name):
                if validate_api_tags(nb):
                    live_count += 1
                    preparation = [
                        c for c in nb.cells if "api_preparation" in c.metadata.get("tags", [])
                    ]
                    self.assertEqual(len(preparation), 1)
                    self.assertIn("client = None", preparation[0].source)
                    guards = [
                        n
                        for n in ast.walk(ast.parse(preparation[0].source))
                        if isinstance(n, ast.If) and ast.unparse(n.test) == "not settings.enabled"
                    ]
                    self.assertEqual(len(guards), 1)
        self.assertEqual(live_count, 15)  # Preface + chapters 2..15; concepts is local.

    def test_default_preparation_clears_old_client_without_constructing_a_new_one(self):
        for path, nb in self.notebooks():
            for cell in nb.cells:
                if "api_preparation" not in cell.metadata.get("tags", []):
                    continue
                with self.subTest(notebook=path.name), patch("openai.OpenAI") as constructor:
                    env = {"settings": SimpleNamespace(enabled=False), "client": object()}
                    with self.assertRaisesRegex(RuntimeError, "RUN_LIVE=True"):
                        exec(cell.source, env)
                    self.assertIsNone(env["client"])
                    constructor.assert_not_called()

    def test_enabled_preparation_creates_client_with_existing_sdk_parameters(self):
        nb = nbformat.read(ROOT / "notebooks/chapters/02_first_agent.ipynb", as_version=4)
        cell = next(c for c in nb.cells if "api_preparation" in c.metadata.get("tags", []))
        with patch("openai.OpenAI") as constructor:
            env = {"settings": SimpleNamespace(enabled=True, api_key="fixture")}
            exec(cell.source, env)
            self.assertIs(env["client"], constructor.return_value)
            self.assertEqual(constructor.call_args.kwargs["api_key"], "fixture")
            self.assertEqual(constructor.call_args.kwargs["max_retries"], 0)

    def test_native_skip_tag_executes_local_cells_and_never_api_cells(self):
        nb = nbformat.v4.new_notebook(
            cells=[
                nbformat.v4.new_code_cell("value = 21"),
                nbformat.v4.new_code_cell(
                    "raise RuntimeError('API cell executed')", metadata={"tags": ["requires_api"]}
                ),
                nbformat.v4.new_code_cell("assert value * 2 == 42"),
            ]
        )
        NotebookClient(nb, timeout=30, skip_cells_with_tag="requires_api").execute()
        self.assertIsNone(nb.cells[1].execution_count)
        self.assertIsNotNone(nb.cells[2].execution_count)

    def test_preparation_requires_an_explicit_enable_check(self):
        nb = nbformat.v4.new_notebook(
            cells=[
                nbformat.v4.new_code_cell(
                    "client = OpenAI()", metadata={"tags": ["requires_api", "api_preparation"]}
                )
            ]
        )
        with self.assertRaisesRegex(ValueError, "check enabled exactly once"):
            validate_api_tags(nb)

    def test_missing_api_tag_is_rejected(self):
        nb = nbformat.v4.new_notebook(
            cells=[nbformat.v4.new_code_cell("client.beta.agents.sessions.retrieve('fixture')")]
        )
        with self.assertRaisesRegex(ValueError, "requires_api"):
            validate_api_tags(nb)

    def test_repeated_mode_guard_is_rejected(self):
        nb = nbformat.v4.new_notebook(
            cells=[nbformat.v4.new_code_cell("if settings.enabled:\n    pass")]
        )
        with self.assertRaisesRegex(ValueError, "only in the preparation"):
            validate_api_tags(nb)

    def test_api_constructor_outside_preparation_is_rejected(self):
        nb = nbformat.v4.new_notebook(
            cells=[
                nbformat.v4.new_code_cell("client = OpenAI()", metadata={"tags": ["requires_api"]})
            ]
        )
        with self.assertRaisesRegex(ValueError, "only in the preparation"):
            validate_api_tags(nb)

    def test_api_preparation_cannot_be_skipped_by_accident(self):
        nb = nbformat.v4.new_notebook(
            cells=[nbformat.v4.new_code_cell("pass", metadata={"tags": ["api_preparation"]})]
        )
        with self.assertRaisesRegex(ValueError, "must have requires_api"):
            validate_api_tags(nb)


if __name__ == "__main__":
    unittest.main()
