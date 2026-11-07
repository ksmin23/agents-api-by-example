"""Add validated standalone Colab notebooks and a ZIP to a static book export."""
from __future__ import annotations
import argparse
from pathlib import Path
import shutil
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_colab import build, render
from build_colab_zip import build as check_zip


def add_downloads(directory, root=ROOT, language='ko'):
    directory, root = Path(directory), Path(root)
    if not (directory / "index.html").is_file():
        raise ValueError("Build the static book first")
    build(root, check=True, language=language)
    check_zip(root, check=True, language=language)
    source = root / "_build/colab" / ('en' if language=='en' else '')
    files = render(root, language)
    target = directory / "downloads/colab"
    expected = {p.relative_to(source) for p in files}
    extra = {p.relative_to(target) for p in target.rglob("*") if p.is_file()} - expected
    if extra:
        raise ValueError("Unexpected download files; prepare a clean HTML export")
    archive = directory / "downloads/colab-notebooks.zip"
    archive.parent.mkdir(parents=True, exist_ok=True)
    for path in sorted(files):
        relative = path.relative_to(source)
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, destination)
    shutil.copy2(root / '_build/packages' / ('colab-notebooks-en.zip' if language=='en' else 'colab-notebooks.zip'), archive)
    return {"standalone_downloads": len(expected) - 1, "archive": "downloads/colab-notebooks.zip"}


if __name__ == "__main__":
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html-directory", type=Path, default=ROOT / "_build/book/sites")
    print(json.dumps(add_downloads(parser.parse_args().html_directory)))
