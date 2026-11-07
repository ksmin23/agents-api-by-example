"""Check standalone exports in fresh kernels outside the source checkout.

Offline execution skips requires_api cells and package installation. For a real
installation check, run an exported bootstrap with a clean Python environment.
This is a functional network guard, not a security sandbox.
"""
from __future__ import annotations
import argparse
import ast
import json
import os
from pathlib import Path
import sys
import tempfile

import nbformat
from nbclient import NotebookClient
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_notebooks import GUARD, validate_api_tags
from build_colab import ROOT, render


def check_exports(root=ROOT, language='ko'):
    directory = root / '_build/colab' / ('en' if language == 'en' else '')
    paths = sorted(p for p in directory.rglob('*.ipynb') if language == 'en' or 'en' not in p.relative_to(directory).parts)
    assert len(paths) == 17, "Expected setup, quickstart and chapters 1–15"
    expected = render(root, language)
    for path in paths:
        assert path.read_text() == expected[path], f"Stale export: {path}"
        nb = nbformat.read(path, as_version=4)
        nbformat.validate(nb)
        validate_api_tags(nb)
        assert nb.metadata.tutorial.standalone
        original = nbformat.read(root / nb.metadata.tutorial.source, as_version=4)
        # Every original execution cell is preserved exactly apart from setup.
        executable = {c.id: c.source for c in original.cells if c.cell_type == "code" and "bootstrap" not in c.metadata.get("tags", [])}
        actual = {c.id: c.source for c in nb.cells if c.id in executable}
        assert executable == actual, path
        for c in nb.cells:
            if c.cell_type != "code":
                continue
            assert not c.outputs and c.execution_count is None
            tree = ast.parse(c.source)
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("tutorial_helpers."):
                    assert "src/" + node.module.replace(".", "/") + ".py" in nb.metadata.tutorial.assets, path
            assert "raw.githubusercontent.com" not in c.source, path
            for node in ast.walk(tree):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    assert node.value not in {"git", "requirements-colab.txt", "colab_bootstrap.py"}, path
        # An absolute source path must never be embedded in exported notebooks.
        assert str(root) not in path.read_text(), path
    return paths


def cleanup_workspaces(notebook):
    """Remove workspaces announced only by the generated root-preparation cell."""
    import shutil
    folders = set()
    for cell in notebook.cells:
        if (cell.cell_type != "code" or "colab_asset" not in cell.metadata.get("tags", [])
            or not cell.id.endswith("-root")):
            continue
        for output in cell.get("outputs", []):
            if output.output_type != "stream":
                continue
            for line in output.text.splitlines():
                if line.startswith("Working directory:"):
                    folder = Path(line.removeprefix("Working directory:").strip())
                    if (folder.parent == Path(tempfile.gettempdir()).resolve()
                        and folder.name.startswith("agents-colab-")):
                        folders.add(folder)
    for folder in folders:
        shutil.rmtree(folder)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument('--language', choices=['ko','en','all'], default='all')
    parser.add_argument("--kernel-python", type=Path, default=Path(sys.executable))
    args = parser.parse_args()
    languages = ['ko','en'] if args.language == 'all' else [args.language]
    paths = [p for language in languages for p in check_exports(language=language)]
    report = {"notebooks": len(paths), "api_cells_executed": 0, "results": []}
    with tempfile.TemporaryDirectory(prefix="colab-isolated-") as temp:
        temporary = Path(temp)
        kernel = temporary / "kernels/standalone"
        kernel.mkdir(parents=True)
        (kernel / "kernel.json").write_text(json.dumps({
            "argv": [str(args.kernel_python.absolute()), "-m", "ipykernel_launcher", "-f", "{connection_file}"],
            "display_name": "Standalone check", "language": "python",
        }))
        env = {k: v for k, v in os.environ.items() if not any(token in k for token in ["API_KEY", "TOKEN", "SECRET"]) and k != "PYTHONPATH"}
        env["JUPYTER_PATH"] = str(temporary)
        os.environ["JUPYTER_PATH"] = str(temporary)
        env["TUTORIAL_OFFLINE_CHECK"] = "1"
        for path in paths:
            nb = nbformat.read(path, as_version=4)
            skipped = validate_api_tags(nb)
            if args.execute:
                work = temporary / ('en-' if 'en' in path.relative_to(ROOT / '_build/colab').parts else 'ko-') / path.stem
                work.mkdir(parents=True)
                nb.cells.insert(0, nbformat.v4.new_code_cell(GUARD + '\nimport shutil\nassert shutil.which("git") is None\n'))
                nb.cells.append(nbformat.v4.new_code_cell('''import hashlib
import tutorial_helpers.common as checked_common
assert Path(checked_common.__file__).resolve().is_relative_to(COLAB_ROOT)
for name, digest in EMBEDDED_MANIFEST.items():
    assert hashlib.sha256((COLAB_ROOT / name).read_bytes()).hexdigest() == digest, name
print("Included files verified; helpers loaded from generated workspace.")
'''.replace("EMBEDDED_MANIFEST", repr(dict(nb.metadata.tutorial.assets)))))
                # No Git executable is available; no checkout exists in the cwd.
                execution_env = dict(env, PATH=str(args.kernel_python.absolute().parent))
                try:
                    NotebookClient(nb, timeout=120, kernel_name="standalone",
                                   resources={"metadata": {"path": str(work)}},
                                   skip_cells_with_tag="requires_api").execute(env=execution_env)
                finally:
                    # Generated root output is distinct from learner diagnostics.
                    cleanup_workspaces(nb)
            report["results"].append({"notebook": str(path.relative_to(ROOT)), "offline_executed": args.execute, "requires_api_skipped": skipped})
            print("OK", path.relative_to(ROOT), flush=True)
    output = ROOT / "outputs/colab-validation"
    output.mkdir(parents=True, exist_ok=True)
    (output / "summary.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"standalone_notebooks": len(paths), "offline_executed": args.execute, "api_cells_executed": 0}))


if __name__ == "__main__":
    main()
