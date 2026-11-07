"""Stage validated artifacts in an already opened Sites checkout; never publish.

Open the checkout with the official Sites source helper before running this.
That helper still owns source commit/push, credentials and archive packaging.
"""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import subprocess
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from artifact_common import ROOT, digest, fingerprint, source_files, tree
from check_artifacts import check as check_artifacts


def prepare(checkout, root=ROOT, *, check=False):
    root, checkout = Path(root).resolve(), Path(checkout).resolve()
    check_artifacts(root, 'sites')
    hosting = checkout / '.openai/hosting.json'
    config = json.loads(hosting.read_text())
    project_id = config['project_id']
    directory = config.get('static', {}).get('directory')
    if not isinstance(project_id, str) or not project_id or directory not in {'dist', 'dist/client', 'out', 'build', '.output/public'}:
        raise ValueError('Existing static Sites identity and supported static.directory are required')
    if not (checkout / '.git').exists():
        raise ValueError('Open the Sites source checkout with its official helper first')
    archive = root / '_build/packages/sites.tar.gz'
    if archive.is_relative_to(checkout):
        raise ValueError('Sites helper archive must be outside its checkout')
    manifest = json.loads((root / '_build/manifest.json').read_text())
    source = root / manifest['targets']['sites']['directory']
    paths = source_files(root)
    snapshot = fingerprint(paths, root)
    provenance = {'project_id': project_id, 'source': manifest['source'],
                  'source_snapshot': snapshot, 'book_sha256': digest(json.dumps(tree(source), sort_keys=True).encode())}
    if check:
        assert tree(checkout / directory) == tree(source), 'Sites static copy differs'
        assert tree(checkout / 'book-source') == snapshot, 'Sites source copy differs'
        assert json.loads((checkout / 'UPSTREAM-SNAPSHOT.json').read_text()) == provenance
    else:
        status = subprocess.run(['git', '-C', str(checkout), 'status', '--porcelain'], capture_output=True, text=True, check=True)
        if status.stdout.strip():
            raise ValueError('Sites checkout has pending changes; preserve or finish them before preparing')
        for name in [directory, 'book-source']:
            path = checkout / name
            if any(parent.is_symlink() for parent in [path, *path.parents] if parent != checkout and parent.is_relative_to(checkout)):
                raise ValueError('Sites destination cannot be a symlink')
            if path.is_dir():
                shutil.rmtree(path)
        shutil.copytree(source, checkout / directory)
        for path in paths:
            destination = checkout / 'book-source' / path.relative_to(root)
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, destination)
        (checkout / 'UPSTREAM-SNAPSHOT.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n')
        records = root / 'outputs/deployments' / datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        records.mkdir(parents=True)
        (records / 'prepared.json').write_text(json.dumps({'project_id': project_id, 'source_inputs_sha256': manifest['source']['inputs_sha256'], 'published': False}, indent=2) + '\n')
    return {'project_id': project_id, 'checkout_path': str(checkout), 'archivePath': str(archive),
            'read_only': check, 'published': False, 'next_step': 'official Sites source helper, then native save/deploy'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkout', type=Path, required=True)
    parser.add_argument('--check', action='store_true')
    args = parser.parse_args()
    print(json.dumps(prepare(args.checkout, check=args.check)))
