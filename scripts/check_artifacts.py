"""Read-only validation of publication inputs, packages and target manifests."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from artifact_common import ROOT, digest, source_state, tree
from build_colab import build as check_colab
from build_colab_zip import build as check_zip
from build_bundles import build as check_bundles
from build_exercise_zip import build as check_exercise_zip
from check_book_output import check_output
from build_colab import render
from book_languages import check as check_languages
from localization import check as check_translations
from book_download_links import check as check_download_links


def check(root=ROOT, target='sites'):
    root = Path(root)
    manifest = json.loads((root / '_build/manifest.json').read_text())
    assert manifest['schema_version'] == 1, 'Unknown artifact manifest schema'
    assert manifest['source']['files'] == source_state(root)['files'], 'Publication inputs changed; rebuild artifacts'
    languages = manifest.get('languages', ['ko'])
    if 'en' in languages:
        check_translations(root)
    for language in languages:
        check_exercise_zip(root, check=True, language=language)
        check_colab(root, check=True, language=language)
        check_zip(root, check=True, language=language)
    check_bundles(root, check=True)
    for component in manifest['components'].values():
        assert tree(root / component['directory']) == component['files'], 'Component artifact changed'
    for name, expected in manifest['packages'].items():
        assert digest((root / '_build/packages' / name).read_bytes()) == expected, 'Colab ZIP changed'
    selected = ['sites', 'pages'] if target == 'all' else [target]
    for name in selected:
        item = manifest['targets'][name]
        directory = root / item['directory']
        assert tree(directory) == item['files'], f'{name} artifact tree changed'
        check_output(directory)
        if 'en' in languages:
            check_languages(directory, item['base_url'], root)
        for language in languages:
            folder = directory / ('en' if language == 'en' else '')
            if 'en' in languages:
                check_download_links(folder, item['base_url'] + ('/en' if language == 'en' else ''))
            package = root / '_build/packages' / ('colab-notebooks-en.zip' if language == 'en' else 'colab-notebooks.zip')
            assert (folder / 'downloads/colab-notebooks.zip').read_bytes() == package.read_bytes(), 'Book ZIP differs'
            exercise = root / '_build/packages' / ('exercise-files-en.zip' if language == 'en' else 'exercise-files.zip')
            assert (folder / 'downloads/exercise-files.zip').read_bytes() == exercise.read_bytes(), 'Exercise ZIP differs'
            colab = root / '_build/colab' / ('en' if language == 'en' else '')
            for path in render(root, language):
                relative = path.relative_to(colab)
                assert (folder / 'downloads/colab' / relative).read_bytes() == path.read_bytes()
        # BASE_URL is recorded per target; the output tree hash prevents mixing targets.
        assert item['base_url'] == ('' if name == 'sites' else manifest['pages_base_url'])
    return {'targets': selected, 'read_only': True, 'source_inputs_unchanged': True}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=['sites', 'pages', 'all'], default='sites')
    print(json.dumps(check(target=parser.parse_args().target)))
