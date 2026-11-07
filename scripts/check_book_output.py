"""Reject developer records in static publication output, including hashed downloads."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from check_tutorial import INTERNAL_DOCUMENTS
BANNED = {Path(p).stem.casefold() for p in INTERNAL_DOCUMENTS} | {"tutorial-improvement", ".work"}


def check_output(directory):
    directory = Path(directory)
    assert (directory / "index.html").is_file(), "Build the book first"
    files = [p for p in directory.rglob("*") if p.is_file()]
    for path in files:
        if path.suffix not in {".md", ".ipynb", ".html", ".json"}:
            continue
        parts = [Path(p).stem.casefold() for p in path.relative_to(directory).parts]
        assert not any(part == name or part.startswith(name + "-") for part in parts for name in BANNED), (
            "Repository-only document exported: " + str(path.relative_to(directory))
        )
    for path in directory.glob("myst.*.json"):
        body = path.read_text()
        assert not any(name in body for name in INTERNAL_DOCUMENTS), "Internal document indexed in " + path.name
    return {"static_files": len(files), "internal_documents_exported": 0}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html-directory", type=Path, default=ROOT / "_build/book/sites")
    args = parser.parse_args()
    print(json.dumps(check_output(args.html_directory)))


if __name__ == "__main__":
    main()
