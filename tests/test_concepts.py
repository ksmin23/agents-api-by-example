"""Chapter 1 is a local concept walkthrough, never an API execution path."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

import nbformat

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_colab import render
from check_notebooks import validate_api_tags
from localization import notebook as translated_notebook
from check_tutorial import check
import run_intro
from test_publication import fixture


class ConceptsTests(unittest.TestCase):
    def test_source_and_english_execute_without_credentials_or_api_client(self):
        source = ROOT/'notebooks/chapters/01_concepts.ipynb'
        variants = [json.loads(source.read_text()), translated_notebook(ROOT, source.relative_to(ROOT).as_posix(), 'en')]
        for language, notebook in zip(['ko', 'en'], variants):
            with self.subTest(language=language), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root/'data').mkdir()
                csv_bytes = (ROOT/'data/sales.csv').read_bytes()
                (root/'data/sales.csv').write_bytes(csv_bytes)
                namespace = {}
                with patch.dict(os.environ, {}, clear=True), \
                        patch('tutorial_helpers.common.project_root', return_value=root), \
                        patch('tutorial_helpers.common.load_settings', side_effect=AssertionError('No settings needed')), \
                        patch('openai.OpenAI', side_effect=AssertionError('No API client allowed')), \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    for cell in notebook['cells']:
                        if cell['cell_type'] == 'code':
                            exec(''.join(cell['source']), namespace)
                self.assertEqual(namespace['csv_text'].encode(), csv_bytes)
                preview = namespace['request_preview']
                self.assertEqual(set(preview), {'agent', 'environment', 'input', 'stream'})
                self.assertEqual(preview['environment'], {'type': 'openai_hosted'})
                self.assertIn(namespace['csv_text'], preview['input'])
                self.assertEqual(preview['agent']['model'], 'MODEL_ID_FOR_CHAPTER_2')
                self.assertEqual({value['type'] for value in namespace['environment_examples'].values()},
                                 {'none', 'openai_hosted', 'self_hosted'})
                self.assertIn('Columns:', output.getvalue())
                self.assertIn('First transaction:', output.getvalue())
                self.assertNotIn('result', namespace)
                self.assertFalse((root/'outputs').exists())

    def test_chapter_has_no_live_configuration_or_api_cells(self):
        notebook = nbformat.read(ROOT/'notebooks/chapters/01_concepts.ipynb', as_version=4)
        self.assertEqual(validate_api_tags(notebook), 0)
        code = '\n'.join(c.source for c in notebook.cells if c.cell_type == 'code')
        for token in ['RUN_LIVE', 'MODEL_OVERRIDE', 'load_settings', 'settings.', 'client.']:
            self.assertNotIn(token, code)
        self.assertFalse(any('live_configuration' in c.metadata.get('tags', []) for c in notebook.cells))
        markdown = '\n'.join(c.source for c in notebook.cells if c.cell_type == 'markdown')
        self.assertNotIn('127,500', markdown)
        self.assertNotIn('30,000 / 75,000', markdown)
        self.assertIn('2장', markdown)
        self.assertIn('5장', markdown)
        self.assertIn('```mermaid', markdown)
        self.assertIn('자기 점검', markdown)

    def test_colab_notice_for_concepts_has_no_live_prerequisites(self):
        for language in ['ko', 'en']:
            with self.subTest(language=language):
                path = ROOT/'_build/colab'/('en' if language == 'en' else '')/'chapters/01_concepts.ipynb'
                notebook = json.loads(render(ROOT, language)[path])
                notice = next(''.join(c['source']) for c in notebook['cells']
                              if ''.join(c['source']).startswith('<!-- colab-link -->'))
                self.assertNotIn('RUN_LIVE', notice)
                self.assertNotIn('Colab Secrets', notice)
                self.assertIn('no API key or model' if language == 'en' else 'API 키나 모델이 필요하지 않습니다', notice)
                guidance = [''.join(c['source']) for c in notebook['cells']
                            if c['cell_type'] == 'markdown' and c['id'].endswith('-guide')]
                self.assertTrue(any('none send API requests' in s or 'API 요청을 보내지 않습니다' in s for s in guidance))

    def test_even_live_runner_request_keeps_chapter_one_offline(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'notebooks/chapters/01_concepts.ipynb'
            path.parent.mkdir(parents=True)
            path.write_bytes((ROOT/'notebooks/chapters/01_concepts.ipynb').read_bytes())
            for requested_live in [False, True]:
                with self.subTest(requested_live=requested_live), \
                        patch.object(run_intro, 'ROOT', root), \
                        patch.object(run_intro, 'update'), \
                        patch.object(run_intro, 'dotenv_values', return_value={}), \
                        patch.object(run_intro, 'NotebookClient') as constructor, \
                        patch('notebook_validation.instrument_notebook') as instrument, \
                        contextlib.redirect_stdout(io.StringIO()) as output:
                    self.assertTrue(run_intro.run(1, requested_live))
                    environment = constructor.return_value.execute.call_args.kwargs['env']
                    self.assertEqual(environment['TUTORIAL_OFFLINE_CHECK'], '1')
                    self.assertNotIn('OPENAI_API_KEY', environment)
                    self.assertEqual(constructor.call_args.kwargs['skip_cells_with_tag'], 'requires_api')
                    self.assertFalse(instrument.call_args.kwargs['live'])
                    self.assertIn('mode=offline', output.getvalue())

    def test_catalog_rejects_adding_live_configuration_to_concepts(self):
        with fixture() as root:
            path = root/'notebooks/chapters/01_concepts.ipynb'
            notebook = json.loads(path.read_text())
            cell = next(c for c in notebook['cells'] if c['cell_type'] == 'code' and 'local_configuration' in c['metadata'].get('tags', []))
            cell['metadata']['tags'] = ['live_configuration']
            path.write_text(json.dumps(notebook))
            with self.assertRaisesRegex(AssertionError, 'Chapter 1'):
                check(root)


if __name__ == '__main__':
    unittest.main()
