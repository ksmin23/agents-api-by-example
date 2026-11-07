"""Validate clean source notebooks, optionally run them with Python networking disabled.

The socket guard prevents accidental Python network requests, not hostile code or
subprocess networking. It is not a security sandbox. No real API check is made.
"""

from __future__ import annotations

import ast
import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
GUARD = """
import os as _os
import socket as _socket
for _name in ("OPENAI_API_KEY", "OPENAI_EXECUTOR_API_KEY", "CODEX_API_KEY", "AZURE_OPENAI_API_KEY", "OPENAI_ADMIN_KEY"):
    _os.environ.pop(_name, None)
_os.environ["RUN_LIVE"] = "false"
_os.environ["TUTORIAL_OFFLINE_CHECK"] = "1"
def _deny_network(*args, **kwargs):
    raise RuntimeError("Offline notebook check: Python network requests are disabled")
_socket.socket.connect = _deny_network
_socket.socket.connect_ex = _deny_network
_socket.create_connection = _deny_network
_socket.getaddrinfo = _deny_network
"""


def validate_api_tags(notebook):
    """Check authoring contracts without interpreting or executing API workflows."""
    preparations = []
    protected = []
    for cell in notebook.cells:
        if cell.cell_type != "code":
            continue
        tags = cell.metadata.get("tags", [])
        tree = ast.parse(cell.source)
        if "requires_api" in tags:
            protected.append(cell)
        if "api_preparation" in tags:
            preparations.append(cell)
            if "requires_api" not in tags:
                raise ValueError("API preparation must have requires_api")
            guards = [
                n
                for n in ast.walk(tree)
                if isinstance(n, ast.If) and ast.unparse(n.test) == "not settings.enabled"
            ]
            if len(guards) != 1:
                raise ValueError("API preparation must check enabled exactly once")
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and ast.unparse(node.test) in {
                "settings.enabled",
                "LIVE_ENABLED",
                "not settings.enabled",
            }:
                if (
                    "api_preparation" not in tags
                    or ast.unparse(node.test) != "not settings.enabled"
                ):
                    raise ValueError("Check API mode only in the preparation cell")
        # Function definitions can mention APIs without calling them during offline setup.
        top_level = ast.Module(
            body=[
                n
                for n in tree.body
                if not isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
            ],
            type_ignores=[],
        )
        for node in ast.walk(top_level):
            if isinstance(node, ast.Call):
                target = ast.unparse(node.func)
                if target == "OpenAI" or target.startswith("client.beta.agents."):
                    if "requires_api" not in tags:
                        raise ValueError("API calls must have requires_api")
                    if target == "OpenAI" and "api_preparation" not in tags:
                        raise ValueError("Create the API client only in the preparation cell")
    if protected and len(preparations) != 1:
        raise ValueError("Exactly one API preparation cell is required")
    return len(protected)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    args = parser.parse_args()
    paths = sorted(
        p for p in (ROOT / "notebooks").rglob("*.ipynb") if ".ipynb_checkpoints" not in p.parts
    )
    if not paths:
        raise RuntimeError("No notebooks found")
    with tempfile.TemporaryDirectory(prefix="agents-tutorial-check-") as temp:
        temp_path = Path(temp)
        kernel_dir = temp_path / "kernels" / "tutorial-check"
        kernel_dir.mkdir(parents=True)
        (kernel_dir / "kernel.json").write_text(
            json.dumps(
                {
                    "argv": [sys.executable, "-m", "ipykernel_launcher", "-f", "{connection_file}"],
                    "display_name": "Tutorial offline check",
                    "language": "python",
                }
            )
        )
        os.environ["JUPYTER_PATH"] = str(temp_path)
        seen_ids = set()
        for path in paths:
            notebook = nbformat.read(path, as_version=4)
            nbformat.validate(notebook)
            api_cells = validate_api_tags(notebook)
            for cell in notebook.cells:
                if cell.id in seen_ids:
                    raise ValueError(f"Duplicate cell id: {cell.id} in {path.name}")
                seen_ids.add(cell.id)
                if cell.cell_type == "code" and (cell.outputs or cell.execution_count is not None):
                    raise ValueError(f"Clear code outputs before committing: {path.name}")
            if args.execute:
                notebook.cells.insert(0, nbformat.v4.new_code_cell(GUARD))
                client = NotebookClient(
                    notebook,
                    timeout=120,
                    kernel_name="tutorial-check",
                    resources={"metadata": {"path": str(ROOT)}},
                    allow_errors=False,
                    skip_cells_with_tag="requires_api",
                )
                env = {
                    key: value
                    for key, value in os.environ.items()
                    if key
                    not in {
                        "OPENAI_API_KEY",
                        "AZURE_OPENAI_API_KEY",
                        "OPENAI_ADMIN_KEY",
                        "OPENAI_EXECUTOR_API_KEY",
                        "CODEX_API_KEY",
                    }
                }
                env["RUN_LIVE"] = "false"
                client.execute(env=env)
                nbformat.write(notebook, temp_path / path.name)
            print(
                f"OK {path.relative_to(ROOT)}"
                + (
                    f" (offline execution; {api_cells} requires_api cells skipped)"
                    if args.execute
                    else f" ({api_cells} requires_api cells)"
                )
            )


if __name__ == "__main__":
    main()
