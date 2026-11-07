"""Keep validation history separate and notebook console messages in English."""
import ast
import io
import json
from pathlib import Path
import re
import sys
import tokenize
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_colab import render
from check_tutorial import check
from test_publication import fixture

HANGUL = re.compile('[가-힣]')


class AuthoringPolicyTests(unittest.TestCase):
    def test_validation_results_cannot_return_to_readme(self):
        self.assertIn('(docs/validation.md)', (ROOT / 'README.md').read_text())
        self.assertNotIn('(PROGRESS.md)', (ROOT / 'README.md').read_text())
        self.assertNotIn('(docs/tutorial-improvement-validation.md)', (ROOT / 'README.md').read_text())
        with fixture() as root:
            p = root / 'README.md'
            p.write_text(p.read_text() + '\n## 검증 결과\n116 tests passed\n')
            with self.assertRaisesRegex(AssertionError, 'PROGRESS.md'):
                check(root)

    def check_code(self, source, location):
        for token in tokenize.generate_tokens(io.StringIO(source).readline):
            if token.type == tokenize.COMMENT:
                self.assertIsNone(HANGUL.search(token.string), location)
        for node in ast.walk(ast.parse(source)):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            if node.func.id not in {'print', 'input', 'RuntimeError', 'ValueError', 'TimeoutError'}:
                continue
            for arg in node.args:
                for value in ast.walk(arg):
                    if isinstance(value, ast.Constant) and isinstance(value.value, str):
                        self.assertIsNone(HANGUL.search(value.value), location)

    def test_source_notebook_comments_and_console_messages_are_english(self):
        for path in (ROOT / 'notebooks').rglob('*.ipynb'):
            if '.ipynb_checkpoints' in path.parts:
                continue
            n = json.loads(path.read_text())
            for cell in n['cells']:
                if cell['cell_type'] == 'code':
                    self.check_code(''.join(cell['source']), f'{path.name}:{cell["id"]}')

    def test_colab_preparation_comments_and_console_messages_are_english(self):
        for path, text in render().items():
            if path.suffix != '.ipynb':
                continue
            n = json.loads(text)
            for cell in n['cells']:
                if cell['cell_type'] == 'code':
                    self.check_code(''.join(cell['source']), f'{path.name}:{cell["id"]}')


if __name__ == '__main__':
    unittest.main()
