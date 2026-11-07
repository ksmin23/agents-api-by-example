"""Build Skill/Plugin ZIPs without modifying sources; --check never writes."""
from __future__ import annotations
import argparse
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from artifact_common import ROOT, archive_bytes, write_or_check


def render_bundles(root=ROOT):
    root = Path(root)
    target = root / 'plugins/sales-reporting'
    copies = [(root / 'examples/mcp/sales_targets_server.py', target / 'servers/sales_targets_server.py'),
              (root / 'data/sales_targets.json', target / 'assets/sales_targets.json')]
    copies += [(p, target / 'skills/csv-report' / p.relative_to(root / 'skills/csv-report'))
               for p in (root / 'skills/csv-report').rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    if any(not b.exists() or a.read_bytes() != b.read_bytes() for a, b in copies):
        raise ValueError('Plugin source copies differ; run scripts/sync_plugin_sources.py explicitly')
    result = {}
    for folder in (root / 'skills/csv-report', target):
        members = {}
        for path in sorted(folder.rglob('*')):
            if '__pycache__' in path.parts or path.suffix == '.pyc':
                continue
            if path.is_symlink():
                raise ValueError('Do not package symlinks')
            if not path.is_file():
                continue
            if path.suffix not in {'.py', '.md', '.json'}:
                raise ValueError('Unexpected bundle file type')
            members[(Path(folder.name) / path.relative_to(folder)).as_posix()] = path.read_bytes()
        result[root / '_build/bundles' / (folder.name + '.zip')] = archive_bytes(members)
    return result


def build(root=ROOT, *, check=False):
    files = render_bundles(root)
    write_or_check(files, check=check)
    return {'bundles': len(files), 'directory': '_build/bundles'}


if __name__ == '__main__':
    import json
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true')
    print(json.dumps(build(check=parser.parse_args().check)))
