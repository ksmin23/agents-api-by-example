"""Exercise archives must work after extraction without the source checkout."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from build_exercise_zip import build
from test_publication import fixture


class ExerciseZipTests(unittest.TestCase):
    def test_archive_runs_with_only_extracted_helpers_and_data(self):
        build()
        with tempfile.TemporaryDirectory() as temp:
            with zipfile.ZipFile(ROOT / '_build/packages/exercise-files.zip') as archive:
                archive.extractall(temp)
            root = Path(temp) / 'agents-api-examples'
            self.assertTrue((root / 'deploy/Dockerfile.private-install.example').is_file())
            notebook = json.loads((root / 'notebooks/quickstart.ipynb').read_text())
            self.assertFalse(notebook.get('metadata', {}).get('tutorial', {}).get('standalone', False))
            code = '''
from pathlib import Path
import importlib
import json
import sys
root = Path.cwd()
sys.path.insert(0, str(root / "src"))
for path in (root / "src/tutorial_helpers").glob("*.py"):
    if path.stem != "__init__":
        module = importlib.import_module("tutorial_helpers." + path.stem)
        assert Path(module.__file__).resolve().is_relative_to(root)
from tutorial_helpers.common import project_root, load_settings
assert project_root() == root
assert load_settings(False).root == root
assert (root / "data/sales.csv").read_text()
assert json.loads((root / "data/sales_targets.json").read_text())
for path in (root / "notebooks").rglob("*.ipynb"):
    notebook = json.loads(path.read_text())
    for cell in notebook["cells"]:
        if "bootstrap" in cell.get("metadata", {}).get("tags", []):
            exec("".join(cell["source"]), {})
'''
            env = {k: v for k, v in os.environ.items() if 'KEY' not in k and k != 'PYTHONPATH'}
            env['TUTORIAL_OFFLINE_CHECK'] = '1'
            # Run from the project folder as documented.
            result = subprocess.run([sys.executable, '-I', '-c', code], cwd=root, env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_deterministic_checks_and_excludes_local_files(self):
        with fixture() as root:
            for folder in ['examples', 'skills', 'plugins', 'deploy', 'scripts']:
                shutil.copytree(ROOT / folder, root / folder, ignore=shutil.ignore_patterns('__pycache__', '.generated'))
            (root / '.env.local').write_text('PRIVATE=secret')
            (root / 'src/.env.local').write_text('PRIVATE=secret')
            build(root)
            build(root, check=True)
            with zipfile.ZipFile(root / '_build/packages/exercise-files.zip') as archive:
                self.assertFalse(any('.env.local' in name or '__pycache__' in name for name in archive.namelist()))
            (root / 'data/sales.csv').write_text('changed')
            with self.assertRaisesRegex(ValueError, 'stale'):
                build(root, check=True)

    def test_english_archive_uses_translated_notebooks(self):
        build(language='en')
        with zipfile.ZipFile(ROOT / '_build/packages/exercise-files-en.zip') as archive:
            notebook = json.loads(archive.read('agents-api-examples/notebooks/quickstart.ipynb'))
            self.assertIn('Quick', ''.join(notebook['cells'][0]['source']))
            self.assertIn('Complete exercise files', archive.read('agents-api-examples/README.md').decode())
