"""Setup confirms local readiness without constructing a client or loading secrets."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from importlib.metadata import PackageNotFoundError

import nbformat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'scripts'))
from build_colab import render
from check_notebooks import validate_api_tags
from check_tutorial import check
from localization import notebook as translated_notebook
from test_publication import fixture


@contextlib.contextmanager
def workspace(*, marker=True, data=True):
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory).resolve()
        if marker:
            (root/'tutorial.json').write_text('{}')
        if data:
            (root/'data').mkdir()
            (root/'data/sales.csv').write_bytes((ROOT/'data/sales.csv').read_bytes())
        nested = root/'notebooks'
        nested.mkdir()
        old = Path.cwd()
        try:
            os.chdir(nested)
            yield root
        finally:
            os.chdir(old)


def source_cell(identifier):
    notebook = nbformat.read(ROOT/'notebooks/setup.ipynb', as_version=4)
    return next(c.source for c in notebook.cells if c.id == identifier)


class SetupWalkthroughTests(unittest.TestCase):
    def test_korean_and_english_execute_from_nested_workdir_without_keys_or_network(self):
        source = 'notebooks/setup.ipynb'
        notebooks = [json.loads((ROOT/source).read_text()), translated_notebook(ROOT, source, 'en')]
        for language, notebook in zip(['ko', 'en'], notebooks):
            with self.subTest(language=language), workspace() as root:
                namespace = {}
                with patch.dict(os.environ, {}, clear=True), \
                        patch('socket.create_connection', side_effect=AssertionError('No network')), \
                        patch('socket.socket.connect', side_effect=AssertionError('No network')), \
                        patch('tutorial_helpers.common.load_settings', side_effect=AssertionError('No API settings')), \
                        patch('tutorial_helpers.common.dotenv_values', side_effect=AssertionError('No credentials')), \
                        patch('openai.OpenAI', side_effect=AssertionError('No client')), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    for cell in notebook['cells']:
                        if cell['cell_type'] == 'code':
                            exec(''.join(cell['source']), namespace)
                self.assertEqual(namespace['root'], root)
                self.assertEqual(namespace['csv_bytes'], (root/'data/sales.csv').read_bytes())
                self.assertEqual(namespace['summary'], {'count':3, 'total':60})
                self.assertFalse((root/'outputs').exists())
                for text in ['Kernel executable:', 'Working directory:', 'OpenAI module location:',
                             'Project root:', 'CSV bytes read:', 'Local preparation complete:']:
                    self.assertIn(text, output.getvalue())
                self.assertNotIn('RUN_LIVE', namespace)

    def test_missing_sdk_has_an_actionable_kernel_installation_error(self):
        with patch('importlib.metadata.version', side_effect=PackageNotFoundError('openai')):
            with self.assertRaisesRegex(RuntimeError, 'uv sync --locked and select .venv'):
                exec(source_cell('setup-packages-code'), {})

    def test_missing_helper_has_an_actionable_preparation_error(self):
        with patch.dict(sys.modules, {'tutorial_helpers.common': None}):
            with self.assertRaisesRegex(RuntimeError, 'Shared helpers are unavailable'):
                exec(source_cell('setup-project-code'), {})

    def test_missing_marker_and_data_stop_before_readiness(self):
        for marker, data, message in [(False, True, 'tutorial.json is missing'), (True, False, 'data/sales.csv is missing')]:
            with self.subTest(marker=marker, data=data), workspace(marker=marker, data=data):
                with self.assertRaisesRegex(FileNotFoundError, message):
                    exec(source_cell('setup-project-code'), {})

    def test_unsupported_python_reports_how_to_change_the_kernel(self):
        with patch.object(sys, 'version_info', (3,10,0)), contextlib.redirect_stdout(io.StringIO()):
            with self.assertRaisesRegex(RuntimeError, 'Select the project .venv'):
                exec(source_cell('00_setup-04'), {'sys':sys})

    def test_colab_setup_and_concepts_are_local_but_quickstart_keeps_api_guidance(self):
        for language in ['ko','en']:
            exports = render(ROOT, language)
            base = ROOT/'_build/colab'/('en' if language == 'en' else '')
            for path in ['setup.ipynb','chapters/01_concepts.ipynb','quickstart.ipynb']:
                with self.subTest(language=language, path=path):
                    notebook = json.loads(exports[base/path])
                    notice = next(''.join(c['source']) for c in notebook['cells']
                                  if ''.join(c['source']).startswith('<!-- colab-link -->'))
                    if path == 'quickstart.ipynb':
                        self.assertIn('RUN_LIVE=True', notice)
                        self.assertIn('Colab Secrets', notice)
                    else:
                        self.assertNotIn('RUN_LIVE', notice)
                        self.assertNotIn('Colab Secrets', notice)
                        self.assertIn('no API key or model' if language=='en' else 'API 키나 모델이 필요하지 않습니다', notice)
                        guides = [''.join(c['source']) for c in notebook['cells'] if c['cell_type']=='markdown']
                        self.assertTrue(any('none send API requests' in text or 'API 요청을 보내지 않습니다' in text for text in guides))

    def test_colab_cleanup_ignores_learner_workdir_output_and_deduplicates_generated_paths(self):
        from check_colab import cleanup_workspaces
        import shutil
        with tempfile.TemporaryDirectory(prefix='agents-colab-') as folder:
            path = Path(folder).resolve()
            generated = nbformat.v4.new_code_cell('', id='fixture-root', metadata={'tags':['colab_asset']})
            generated.outputs = [nbformat.v4.new_output('stream', name='stdout',
                text=f'Working directory: {path}\nWorking directory: {path}\n')]
            learner = nbformat.v4.new_code_cell('', id='learner-kernel')
            learner.outputs = [nbformat.v4.new_output('stream', name='stdout',
                text=f'Working directory: {path}\n')]
            notebook = nbformat.v4.new_notebook(cells=[generated, learner])
            with patch('shutil.rmtree', wraps=shutil.rmtree) as remove:
                cleanup_workspaces(notebook)
                remove.assert_called_once_with(path)
            self.assertFalse(path.exists())

    def test_setup_has_no_api_switch_and_catalog_rejects_adding_one(self):
        notebook = nbformat.read(ROOT/'notebooks/setup.ipynb', as_version=4)
        self.assertEqual(validate_api_tags(notebook), 0)
        code = '\n'.join(c.source for c in notebook.cells if c.cell_type=='code')
        self.assertNotIn('RUN_LIVE', code)
        self.assertNotIn('load_settings', code)
        with fixture() as root:
            path = root/'notebooks/setup.ipynb'
            changed = json.loads(path.read_text())
            changed['cells'].append(dict(nbformat.v4.new_code_cell('RUN_LIVE = False')))
            path.write_text(json.dumps(changed))
            with self.assertRaisesRegex(AssertionError, 'Setup has no live-execution switch'):
                check(root)


if __name__ == '__main__':
    unittest.main()
