"""Use deployment-root-relative download links in rendered HTML and client JSON."""
from __future__ import annotations

import json
from pathlib import Path
import re
from urllib.parse import unquote, urlsplit
from book_languages import ReaderLinks

SITE_DOWNLOAD = re.compile(r'https://[^/\s"<>\\)]+\.openai\.chatgpt\.site/downloads/')


def documents(directory):
    for path in Path(directory).rglob('*'):
        relative = path.relative_to(directory)
        # Downloaded notebooks are exact copies, and English is checked separately.
        if relative.parts[0] in {'downloads', 'en'}:
            continue
        if path.is_file() and path.suffix in {'.html', '.json'}:
            yield path


def relativize(directory, base=''):
    for path in documents(directory):
        text = path.read_text()
        updated = SITE_DOWNLOAD.sub(base + '/downloads/', text)
        if path.suffix == '.json':
            value = json.loads(updated)
            if mark_downloads(value, base):
                updated = json.dumps(value, ensure_ascii=False)
        else:
            context = hydration(updated)
            if context and mark_downloads(context[2], base):
                start, end, value = context
                payload = json.dumps(value, ensure_ascii=False)
                for literal, escaped in [('<', '\\u003c'), ('>', '\\u003e'),
                                         ('&', '\\u0026'), ('\u2028', '\\u2028'),
                                         ('\u2029', '\\u2029')]:
                    payload = payload.replace(literal, escaped)
                updated = updated[:start] + payload + updated[end:]
        if updated != text:
            path.write_text(updated)


def hydration(text):
    marker = 'window.__remixContext = '
    if marker not in text:
        return None
    start = text.index(marker) + len(marker)
    value, end = json.JSONDecoder().raw_decode(text[start:])
    return start, start + end, value


def mark_downloads(value, base):
    count = 0
    if isinstance(value, dict):
        if value.get('type') == 'link' and str(value.get('url', '')).startswith(base + '/downloads/'):
            # MyST otherwise infers an internal page link after the URL becomes relative.
            # Keep file downloads outside the client router and BASE_URL rewriting.
            # Keep the original SSR external-link icon to avoid a hydration mismatch.
            value.update(internal=False, static=False)
            count += 1
        for item in value.values():
            count += mark_downloads(item, base)
    elif isinstance(value, list):
        count += sum(mark_downloads(item, base) for item in value)
    return count


def json_links(value):
    if isinstance(value, dict):
        if value.get('type') == 'link' and '/downloads/' in str(value.get('url', '')):
            assert value.get('internal') is False and value.get('static') is False, 'Download enters MyST page router'
        for key, item in value.items():
            if key in {'url', 'href'} and isinstance(item, str):
                yield item
            else:
                yield from json_links(item)
    elif isinstance(value, list):
        for item in value:
            yield from json_links(item)


def check(directory, base=''):
    directory = Path(directory)
    count = 0
    for path in documents(directory):
        text = path.read_text()
        assert not SITE_DOWNLOAD.search(text), f'Hosted download URL remains: {path}'
        if path.suffix == '.json':
            urls = json_links(json.loads(text))
        else:
            parser = ReaderLinks()
            parser.feed(text)
            context = hydration(text)
            urls = [*parser.urls, *(json_links(context[2]) if context else [])]
        for url in urls:
            if '/downloads/' not in url:
                continue
            assert url.startswith(base + '/downloads/'), f'Incorrect download base: {url}'
            pathname = unquote(urlsplit(url).path)
            target = (directory / pathname[len(base) + 1:]).resolve()
            assert target.is_relative_to(directory.resolve()), f'Download escaped root: {url}'
            assert target.is_file(), f'Missing download: {url}'
            count += 1
    assert count > 0, 'No rendered download links found'
    return {'download_links_checked': count, 'base_url': base}
