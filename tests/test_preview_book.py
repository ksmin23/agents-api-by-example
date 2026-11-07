"""Publication-relative downloads and local hosting at real deployment prefixes."""
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import sys
import tempfile
from threading import Thread
import unittest
from unittest.mock import patch
from urllib.error import HTTPError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from book_download_links import relativize, check, hydration
from preview_book import handler, serve


class PreviewTests(unittest.TestCase):
    def test_html_and_client_json_downloads_respect_all_four_mounts(self):
        for base in ['', '/en', '/agents-api-by-example', '/agents-api-by-example/en']:
            with self.subTest(base=base), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                download = root/'downloads/colab/quickstart.ipynb'
                download.parent.mkdir(parents=True)
                payload = b'Original notebook: https://example.openai.chatgpt.site/downloads/test'
                download.write_bytes(payload)
                url = 'https://example.openai.chatgpt.site/downloads/colab/quickstart.ipynb'
                context = json.dumps({'type':'link', 'url':url, 'children':[{'type':'text','value':'</script>'}]}).replace('<', '\\u003c')
                (root/'index.html').write_text(f'<a href="{url}">Download</a><script>window.__remixContext = {context};</script>')
                (root/'index.json').write_text(json.dumps({'children':[{'type':'link','url':url}]}))
                relativize(root, base)
                self.assertEqual(check(root, base)['download_links_checked'], 3)
                expected = base + '/downloads/colab/quickstart.ipynb'
                self.assertIn(f'href="{expected}"', (root/'index.html').read_text())
                self.assertEqual(json.loads((root/'index.json').read_text())['children'][0]['url'], expected)
                self.assertIs(json.loads((root/'index.json').read_text())['children'][0]['internal'], False)
                embedded = hydration((root/'index.html').read_text())[2]
                self.assertIs(embedded['static'], False)
                self.assertEqual(embedded['children'][0]['value'], '</script>')
                self.assertIn('\\u003c/script', (root/'index.html').read_text())
                self.assertEqual(download.read_bytes(), payload)

    def test_download_check_rejects_hosted_urls_and_missing_files(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            page = root/'index.html'
            page.write_text('<a href="https://example.openai.chatgpt.site/downloads/missing.zip">ZIP</a>')
            with self.assertRaisesRegex(AssertionError, 'Hosted download URL'):
                check(root)
            relativize(root)
            with self.assertRaisesRegex(AssertionError, 'Missing download'):
                check(root)

    def test_server_preserves_pages_redirects_and_download_bytes(self):
        for base in ['', '/agents-api-by-example']:
            with self.subTest(base=base), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                (root/'index.html').write_text('Korean')
                (root/'en').mkdir()
                state = {'state':{'loaderData':{'routes/$':{'title':'English'}}}}
                english = 'English<script>window.__remixContext = '+json.dumps(state)+';</script>'
                (root/'en/index.html').write_text(english)
                (root/'downloads').mkdir()
                (root/'downloads/test.zip').write_bytes(b'zip-bytes')
                factory = handler(root, base)
                factory.func.log_message = lambda *args: None
                with ThreadingHTTPServer(('127.0.0.1', 0), factory) as server:
                    thread = Thread(target=server.serve_forever, daemon=True)
                    thread.start()
                    origin = f'http://127.0.0.1:{server.server_port}'
                    try:
                        with urlopen(origin + '/') as response:
                            self.assertEqual(response.url, origin + base + '/')
                            self.assertEqual(response.read(), b'Korean')
                        with urlopen(origin + base + '/en') as response:
                            self.assertEqual(response.url, origin + base + '/en/')
                            self.assertEqual(response.read(), english.encode())
                        with urlopen(origin + base + '/en/?_data=routes%2F%24') as response:
                            self.assertEqual(response.headers.get_content_type(), 'application/json')
                            self.assertEqual(json.load(response), {'title':'English'})
                        with self.assertRaises(HTTPError) as error:
                            urlopen(origin + base + '/en/?_data=missing')
                        self.assertEqual(error.exception.code, 404)
                        url = origin + base + '/downloads/test.zip'
                        with urlopen(url) as response:
                            self.assertEqual(response.read(), b'zip-bytes')
                            self.assertEqual(response.headers['Cache-Control'], 'no-store')
                        with urlopen(Request(url, method='HEAD')) as response:
                            self.assertEqual(response.status, 200)
                        if base:
                            with self.assertRaises(HTTPError) as error:
                                urlopen(origin + '/en/')
                            self.assertEqual(error.exception.code, 404)
                    finally:
                        server.shutdown()
                        thread.join()

    def test_preview_rejects_stale_artifacts_before_starting_server(self):
        with patch('check_artifacts.check', side_effect=AssertionError('stale')):
            with patch('preview_book.ThreadingHTTPServer') as server:
                with self.assertRaisesRegex(AssertionError, 'stale'):
                    serve(ROOT)
                server.assert_not_called()


if __name__ == '__main__':
    unittest.main()
