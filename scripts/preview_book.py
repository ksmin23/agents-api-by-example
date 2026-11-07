"""Serve validated publication artifacts locally with the production URL prefix."""
from __future__ import annotations

import argparse
import json
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
from artifact_common import ROOT
from book_download_links import hydration


def handler(directory, base=''):
    class PreviewHandler(SimpleHTTPRequestHandler):
        def end_headers(self):
            self.send_header('Cache-Control', 'no-store')
            super().end_headers()

        def translate_path(self, path):
            return super().translate_path(path[len(base):])

        def do_GET(self):
            self.serve_request(super().do_GET)

        def do_HEAD(self):
            self.serve_request(super().do_HEAD)

        def serve_request(self, serve):
            original = self.path
            parsed = urlsplit(original)
            if base and parsed.path in {'/', base}:
                self.send_response(302)
                self.send_header('Location', base + '/' + ('?' + parsed.query if parsed.query else ''))
                self.end_headers()
                return
            if not parsed.path.startswith(base + '/'):
                self.send_error(404, 'Path is outside the publication base')
                return
            data_route = parse_qs(parsed.query).get('_data')
            if data_route:
                # Remix client navigation requests the same loader data embedded in
                # the prebuilt HTML. Serve it as JSON rather than returning HTML.
                page = Path(self.translate_path(original))
                if page.is_dir():
                    page /= 'index.html'
                context = hydration(page.read_text()) if page.is_file() and page.suffix == '.html' else None
                loaders = context[2].get('state', {}).get('loaderData', {}) if context else {}
                if data_route[0] not in loaders:
                    self.send_error(404, 'No static loader data for this route')
                    return
                payload = json.dumps(loaders[data_route[0]], ensure_ascii=False).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.send_header('X-Remix-Response', 'yes')
                self.end_headers()
                if self.command != 'HEAD':
                    self.wfile.write(payload)
                return
            serve()

    return partial(PreviewHandler, directory=str(directory))


def serve(root=ROOT, target='sites', port=8000, rebuild=False):
    from check_artifacts import check
    if rebuild:
        from build_artifacts import build
        build(root, target)
    check(root, target)
    manifest = json.loads((root / '_build/manifest.json').read_text())
    item = manifest['targets'][target]
    directory = root / item['directory']
    base = item['base_url']
    with ThreadingHTTPServer(('127.0.0.1', port), handler(directory, base)) as server:
        origin = f'http://127.0.0.1:{server.server_port}' + base
        print(f'Korean: {origin}/\nEnglish: {origin}/en/\nStop: Ctrl+C', flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=['sites', 'pages'], default='sites')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--build', action='store_true', help='Rebuild the selected target before serving')
    args = parser.parse_args()
    try:
        serve(target=args.target, port=args.port, rebuild=args.build)
    except (AssertionError, ValueError, FileNotFoundError, OSError) as error:
        parser.exit(1, f'Preview unavailable: {error}\nRebuild: uv run --group docs python scripts/preview_book.py --build --target {args.target}\n')
