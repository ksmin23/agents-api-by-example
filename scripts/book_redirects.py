"""Create compatibility pages after a static Jupyter Book build; never change its TOC."""
from __future__ import annotations

import argparse
import html
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
MARKER = '<meta name="tutorial-redirect" content="true">'


def build_redirects(directory, *, mapping=None, base_url=""):
    directory = Path(directory)
    if mapping is None:
        mapping = json.loads((ROOT / "book-redirects.json").read_text())
    if not re.fullmatch(r"(?:/[A-Za-z0-9_.-]+)*", base_url) or any(
        part in {".", ".."} for part in base_url.split("/")
    ):
        raise ValueError("Use a root-relative base URL")
    plans = []
    for old, target in mapping.items():
        if not all(re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", s) for s in (old, target)):
            raise ValueError("Compatibility routes must be simple slugs")
        if old == target:
            raise ValueError("A compatibility route cannot redirect to itself")
        if not (directory / target / "index.html").is_file():
            raise ValueError(f"Missing canonical page: {target}")
        destination = directory / old / "index.html"
        if destination.exists() and MARKER not in destination.read_text():
            raise ValueError(f"Refusing to overwrite a content page: {old}")
        url = base_url + "/" + target + "/"
        plans.append((destination, url))
    for destination, url in plans:
        document = (
            '<!doctype html><html lang="ko"><head><meta charset="utf-8">'
            + MARKER
            + '<meta name="robots" content="noindex">'
            + '<meta http-equiv="refresh" content="0;url=' + html.escape(url, quote=True) + '">'
            + '<title>통합된 학습 페이지로 이동</title></head><body>'
            + '<p>설명과 실습을 하나의 페이지로 통합했습니다. '
            + '<a href="' + html.escape(url, quote=True) + '">학습 페이지 열기</a></p>'
            + '<script>location.replace(' + json.dumps(url)
            + ' + location.search + location.hash);</script></body></html>\n'
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(document)
    return {"compatibility_pages": len(plans), "base_url": base_url}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--html-directory", type=Path, default=ROOT / "_build/book/sites")
    parser.add_argument("--base-url", default="")
    args = parser.parse_args()
    print(json.dumps(build_redirects(args.html_directory, base_url=args.base_url)))


if __name__ == "__main__":
    main()
