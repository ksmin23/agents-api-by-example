"""Extract exercise ZIPs outside the checkout and run notebooks without API calls."""
from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile
from artifact_common import ROOT
from build_exercise_zip import build


def check(root=ROOT, language='ko'):
    root = Path(root)
    build(root, check=True, language=language)
    name = 'exercise-files-en.zip' if language == 'en' else 'exercise-files.zip'
    with tempfile.TemporaryDirectory(prefix='exercise-isolated-') as folder:
        with zipfile.ZipFile(root / '_build/packages' / name) as archive:
            archive.extractall(folder)
        extracted = Path(folder) / 'agents-api-examples'
        env = {k: v for k, v in os.environ.items() if not any(token in k for token in ['API_KEY', 'TOKEN', 'SECRET'])}
        env['PYTHONPATH'] = str(extracted / 'src')
        env['TUTORIAL_OFFLINE_CHECK'] = '1'
        subprocess.run([sys.executable, '-c', '''from pathlib import Path
import tutorial_helpers.common as common
assert Path(common.__file__).resolve().is_relative_to(Path.cwd())
assert common.project_root() == Path.cwd()
'''], cwd=extracted, env=env, check=True)
        subprocess.run([sys.executable, str(extracted / 'scripts/check_notebooks.py'), '--execute'], cwd=extracted, env=env, check=True)
    return {'language': language, 'isolated_execution': True, 'api_cells_executed': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--language', choices=['ko', 'en', 'all'], default='all')
    args = parser.parse_args()
    print(json.dumps([check(language=lang) for lang in (['ko', 'en'] if args.language == 'all' else [args.language])]))
