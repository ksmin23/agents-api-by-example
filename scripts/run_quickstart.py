"""Execute the actual Quickstart notebook in a fresh local kernel (explicit --live)."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

from dotenv import dotenv_values
import nbformat
from nbclient import NotebookClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live', action='store_true', required=True,
                        help='Authorize a paid model/sandbox run, then delete the created session')
    args = parser.parse_args()
    source = ROOT / 'notebooks/quickstart.ipynb'
    notebook = nbformat.read(source, as_version=4)
    nbformat.validate(notebook)
    from check_notebooks import validate_api_tags
    validate_api_tags(notebook)
    switches = 0
    for cell in notebook.cells:
        if 'live_configuration' in cell.metadata.get('tags', []):
            if cell.source.count('RUN_LIVE = False') != 1:
                parser.error('Expected one default-off live switch in the source notebook')
            cell.source = cell.source.replace('RUN_LIVE = False', 'RUN_LIVE = True')
            switches += 1
    if switches != 1:
        parser.error('Could not identify the live configuration cell')

    from notebook_validation import instrument_notebook
    instrument_notebook(notebook, "preface", live=True)
    destination = ROOT / 'outputs/quickstart-validation/quickstart.executed.ipynb'
    destination.parent.mkdir(parents=True, exist_ok=True)
    failure = None
    with tempfile.TemporaryDirectory(prefix='agents-quickstart-live-') as temp:
        directory = Path(temp) / 'kernels/tutorial-live'
        directory.mkdir(parents=True)
        (directory / 'kernel.json').write_text(json.dumps({
            'argv': [sys.executable, '-m', 'ipykernel_launcher', '-f', '{connection_file}'],
            'display_name': 'Tutorial live validation', 'language': 'python',
        }))
        previous = os.environ.get('JUPYTER_PATH')
        os.environ['JUPYTER_PATH'] = temp
        env = dict(os.environ)
        env.pop('TUTORIAL_OFFLINE_CHECK', None)
        env.pop('OPENAI_LOG', None)
        client = NotebookClient(notebook, timeout=360, kernel_name='tutorial-live',
                                resources={'metadata': {'path': str(ROOT)}}, allow_errors=False)
        print('Executing the notebook with live API access; source notebook stays default-off.', flush=True)
        try:
            client.execute(env=env)
        except Exception as error:
            failure = type(error).__name__
        finally:
            if previous is None:
                os.environ.pop('JUPYTER_PATH', None)
            else:
                os.environ['JUPYTER_PATH'] = previous

    # Never persist a notebook containing the actual secret, including error output.
    serialized = nbformat.writes(notebook)
    local = dotenv_values(ROOT / '.env.local')
    keys = [local.get('OPENAI_API_KEY'), os.environ.get('OPENAI_API_KEY')]
    if any(key and key in serialized for key in keys):
        raise RuntimeError('Secret detected in notebook output; refusing to save it')
    destination.write_text(serialized)
    print('Executed notebook:', destination.relative_to(ROOT), flush=True)
    if failure:
        print('Notebook execution failed:', failure, flush=True)
        print('Inspect the saved notebook and outputs/quickstart/<run_id>/creation.json and summary.json for cleanup status.', flush=True)
        return 1
    print('PASS: notebook completed; inspect its summary for result and deletion verification.', flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
