"""Set GitHub/Colab links without network requests or Git mutations."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from os.path import relpath

ROOT = Path(__file__).resolve().parents[1]


def render_updates(root: Path, repository: str | None, ref: str) -> dict[Path, str]:
    if repository and not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Use OWNER/REPOSITORY, not a URL")
    if not ref or ref.startswith('-') or any(c.isspace() for c in ref):
        raise ValueError("Use a nonempty Git ref without whitespace")
    updates = {root / 'tutorial.json': json.dumps(
        {'repository': repository, 'ref': ref}, ensure_ascii=False, indent=2) + '\n'}
    badges = []
    def notebook_order(path):
        priority = 0 if path.name == 'setup.ipynb' else 1 if path.name == 'quickstart.ipynb' else 2
        return priority, path.as_posix()
    paths = (p for p in (root / 'notebooks').rglob('*.ipynb') if '.ipynb_checkpoints' not in p.parts)
    for path in sorted(paths, key=notebook_order):
        notebook = json.loads(path.read_text())
        local_only = notebook.get('metadata', {}).get('tutorial', {}).get('execution') == 'local_docker'
        label = '읽기용 · 실습은 로컬 Docker' if local_only else 'Colab 업로드용'
        guide = relpath(root / "docs/colab.md", path.parent).replace("\\", "/")
        link = f'<!-- colab-link -->\n[독립 실행본 다운로드 안내]({guide}) · {label}\n'
        if not path.name.startswith('_'):
            title = ''.join(notebook['cells'][0]['source']).splitlines()[0].removeprefix('# ')
            filename = path.relative_to(root / "notebooks").as_posix()
            badges.append(f'- {title} · `{filename}` · {label}')
        count = 0
        for cell in notebook['cells']:
            source = ''.join(cell['source'])
            if source.startswith('<!-- colab-link -->'):
                cell['source'] = link.splitlines(keepends=True)
                count += 1
        if count != 1:
            raise ValueError(f'Expected one Colab marker: {path.name}')
        updates[path] = json.dumps(notebook, ensure_ascii=False, indent=1) + '\n'

    readme = root / 'README.md'
    body = '\n'.join(badges)
    content, count = re.subn(
        r'<!-- colab-links:start -->.*?<!-- colab-links:end -->',
        lambda _: f'<!-- colab-links:start -->\n{body}\n<!-- colab-links:end -->',
        readme.read_text(), flags=re.DOTALL)
    if count != 1:
        raise ValueError('Missing README link markers')
    updates[readme] = content
    myst = root / 'myst.yml'
    line = (f'  github: https://github.com/{repository} # managed-repository'
            if repository else '  # managed-repository')
    content, count = re.subn(r'^  .*# managed-repository$', lambda _: line,
                             myst.read_text(), flags=re.MULTILINE)
    if count != 1:
        raise ValueError('Missing myst.yml repository marker')
    updates[myst] = content
    return updates


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--repository', help='GitHub OWNER/REPOSITORY')
    parser.add_argument('--ref', help='Branch, tag or commit SHA (initial default: main)')
    parser.add_argument('--check', action='store_true', help='Check existing configuration without writes')
    parser.add_argument('--require-repository', action='store_true', help='Require a real repository setting')
    args = parser.parse_args()
    config = json.loads((ROOT / 'tutorial.json').read_text())
    repository = args.repository if args.repository is not None else config['repository']
    ref = args.ref if args.ref is not None else config['ref']
    if args.require_repository and not repository:
        parser.error('Run with --repository OWNER/REPOSITORY before publishing')
    if not args.check and not args.repository:
        parser.error('--repository OWNER/REPOSITORY is required to update links')
    updates = render_updates(ROOT, repository, ref)
    changed = [path for path, content in updates.items() if path.read_text() != content]
    if args.check:
        if changed:
            parser.error('Out-of-sync files: ' + ', '.join(str(p.relative_to(ROOT)) for p in changed))
        print('Repository and Colab configuration are consistent.')
    else:
        for path, content in updates.items():
            path.write_text(content)
        print(f'Configured {repository} at {ref}; no remote changes made.')


if __name__ == '__main__':
    main()
