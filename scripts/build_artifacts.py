"""Build publication artifacts in isolated MyST workspaces; never publish."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
sys.path.insert(0, str(Path(__file__).resolve().parent))
from artifact_common import ROOT, fingerprint, source_files, source_state, tree
from build_colab import build as build_colab, render as render_colab
from build_colab_zip import build as build_zip
from build_bundles import build as build_bundles, render_bundles
from build_exercise_zip import build as build_exercise_zip
from book_redirects import build_redirects
from book_colab_downloads import add_downloads
from check_book_output import check_output
from localization import check as check_translations, materialize
from book_languages import assemble
from book_download_links import relativize, check as check_download_links
from pages_base_url import pages_base_url


def build(root=ROOT, target='sites'):
    root = Path(root).resolve()
    config = json.loads((root / 'tutorial.json').read_text())
    repository = config['repository']
    page_base = pages_base_url(repository) if repository else None
    if target in {'pages', 'all'}:
        actual = os.environ.get('GITHUB_REPOSITORY')
        if not repository or (actual and actual.casefold() != repository.casefold()):
            raise ValueError('tutorial.json repository must match GITHUB_REPOSITORY')
    before = source_state(root)
    check_translations(root)
    for language in ["ko", "en"]:
        build_colab(root, language=language); build_zip(root, language=language)
        build_exercise_zip(root, language=language)
    build_bundles(root)
    existing = root / '_build/manifest.json'
    # Carry over another target only if its inputs and its final bytes still match.
    old = json.loads(existing.read_text()) if existing.exists() else {}
    targets = {}
    if old.get('source', {}).get('files') == before['files']:
        targets = {name: item for name, item in old.get('targets', {}).items()
                   if tree(root / item['directory']) == item['files']}
    work = root / '_build/work'
    work.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    logs = root / 'outputs/validation' / ('build-' + run_id)
    logs.mkdir(parents=True)
    selected = ['sites', 'pages'] if target == 'all' else [target]
    for name in selected:
        base = '' if name == 'sites' else page_base
        with tempfile.TemporaryDirectory(prefix='assemble-' + name + '-', dir=work) as combined:
            combined = Path(combined)
            for language in ['ko', 'en']:
                locale_base = base + ('/en' if language == 'en' else '')
                with tempfile.TemporaryDirectory(prefix=name + '-' + language + '-', dir=work) as temp:
                    workspace = Path(temp)
                    for path in source_files(root):
                        destination = workspace / path.relative_to(root)
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(path, destination)
                    if language == 'en':
                        materialize(root, workspace)
                    cache = root / '_build/templates'
                    if cache.is_dir():
                        shutil.copytree(cache, workspace / '_build/templates')
                    subprocess.run(['git', 'init', '--quiet', '--initial-branch=main', str(workspace)], check=True)
                    command = [str(Path(sys.executable).parent / 'jupyter'), 'book', 'build', '--html']
                    with (logs / (name + '-' + language + '.log')).open('w') as log:
                        subprocess.run(command, cwd=workspace, env=dict(os.environ, BASE_URL=locale_base, GIT_CEILING_DIRECTORIES=str(work)),
                                       stdout=log, stderr=subprocess.STDOUT, check=True)
                    if not cache.exists() and (workspace / '_build/templates').is_dir():
                        shutil.copytree(workspace / '_build/templates', cache)
                    html = workspace / '_build/html'
                    relativize(html, locale_base)
                    if language == 'ko':
                        build_redirects(html, mapping=json.loads((root / 'book-redirects.json').read_text()), base_url=base)
                    add_downloads(html, root, language)
                    check_download_links(html, locale_base)
                    check_output(html)
                    shutil.copytree(html, combined / ('en' if language == 'en' else ''), dirs_exist_ok=True)
            assemble(combined, base, root)
            check_output(combined)
            destination = root / '_build/book' / name
            if destination.is_symlink():
                raise ValueError('Book destination cannot be a symlink')
            if destination.is_dir():
                shutil.rmtree(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(combined, destination)
            targets[name] = {'directory': f'_build/book/{name}', 'base_url': base, 'files': tree(destination)}
    assert before['files'] == source_state(root)['files'], 'Build modified publication inputs'
    components = {}
    for name, directory, paths in [
        ('colab', '_build/colab', render_colab(root)),
        ('bundles', '_build/bundles', render_bundles(root)),
    ]:
        expected = fingerprint(paths, root / directory)
        if name == 'colab':
            expected.update(fingerprint(render_colab(root, 'en'), root / directory))
        assert tree(root / directory) == expected, 'Unexpected component files: ' + directory
        components[name] = {'directory': directory, 'files': expected}
    from artifact_common import digest
    manifest = {'schema_version': 1, 'languages': ['ko', 'en'], 'source': before, 'pages_base_url': page_base,
                'components': components, 'targets': targets,
                'packages': {name: digest((root / '_build/packages' / name).read_bytes()) for name in ['colab-notebooks.zip', 'colab-notebooks-en.zip', 'exercise-files.zip', 'exercise-files-en.zip']}}
    existing.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n')
    from check_artifacts import check
    check(root, target)
    (logs / 'summary.json').write_text(json.dumps({'targets': selected, 'success': True}) + '\n')
    return {'targets': selected, 'manifest': '_build/manifest.json', 'log_directory': str(logs.relative_to(root))}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target', choices=['sites', 'pages', 'all'], default='sites')
    print(json.dumps(build(target=parser.parse_args().target)))
