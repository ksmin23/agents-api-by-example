"""Static catalog/publication checks; no installs, Docker, or API calls."""
import argparse
import ast
import json
from pathlib import Path
import re
import tomllib
from urllib.parse import unquote, urlparse

ROOT = Path(__file__).resolve().parents[1]

INTERNAL_DOCUMENTS = frozenset({
    "PROGRESS.md", "todo.md", "docs/artifact-pipeline.md", "docs/tutorial-improvement-plan.md",
    "docs/tutorial-improvement-validation.md", "docs/api-direct-refactor.md",
    "docs/final-review.md", "docs/authoring.md", "docs/publishing.md",
    "docs/localization.md",
})
HAN = re.compile("[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff\U00020000-\U0002fa1f\U00030000-\U000323af]")


RETIRED_GUIDE_PATTERNS = (
    'docs/chapters/*.md', 'docs/intro/*.md', 'docs/deployment/*.md',
    'docs/extensions/[0-9]*.md', 'docs/getting-started.md', 'docs/architecture.md',
)


def retired_guides(root):
    return sorted({p.relative_to(root).as_posix()
                   for pattern in RETIRED_GUIDE_PATTERNS for p in root.glob(pattern) if p.is_file()})


def document_body(path):
    if path.suffix == ".ipynb":
        notebook = json.loads(path.read_text())
        return "\n".join("".join(c["source"]) for c in notebook["cells"] if c["cell_type"] == "markdown")
    return path.read_text()


def check_reader_pages(root, toc):
    """Follow local document links so hidden work records cannot enter exports."""
    root = root.resolve()
    queue = [root / p for p in toc]
    visited = set()
    while queue:
        path = queue.pop().resolve()
        if path in visited:
            continue
        visited.add(path)
        relative = path.relative_to(root).as_posix()
        assert ".work" not in path.relative_to(root).parts and relative not in INTERNAL_DOCUMENTS, f"Repository-only document linked from the book: {relative}"
        assert path.stem.casefold() not in {"progress", "todo"}, f"Repository-only document: {relative}"
        body = document_body(path)
        assert not HAN.search(body), f"Use Korean or English in the book: {relative}"
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)', re.sub(r'```.*?```', '', body, flags=re.DOTALL)):
            target = target.strip().split(' "', 1)[0].strip('<>')
            parsed = urlparse(target)
            if parsed.scheme or target.startswith(('#', '/')):
                continue
            child = (path.parent / unquote(parsed.path)).resolve()
            if child.suffix in {".md", ".ipynb"}:
                assert child.is_file(), f"Missing local document linked from {relative}: {target}"
                queue.append(child)
    return len(visited)

def check(root=ROOT):
    root = Path(root)
    readme = (root / 'README.md').read_text()
    assert not re.search(r'^#{1,6}\s+(?:실행\s+)?검증\s+(?:범위|결과)\s*$', readme, re.MULTILINE), 'Record validation results in local .work/PROGRESS.md, not README.md'
    config = json.loads((root / 'tutorial.json').read_text())
    toc = re.findall(r'^ *- file: (.+)$', (root / 'myst.yml').read_text(), flags=re.MULTILINE)
    assert toc and len(toc) == len(set(toc)), 'TOC has missing/duplicate entries'
    assert all((root / p).is_file() for p in toc), 'TOC references a missing file'
    assert toc[:3] == ['index.md', 'notebooks/setup.ipynb', 'notebooks/quickstart.ipynb'], 'Startup pages must be unnumbered notebooks'
    assert not any(re.match(r'docs/(intro|extensions|deployment)/[0-9]', p) for p in toc), 'Use canonical notebook pages, not duplicate chapter documents'
    assert 'docs/getting-started.md' not in toc and 'docs/architecture.md' not in toc, 'Startup explanations belong in notebooks'
    assert not retired_guides(root), 'Retired guide files must stay removed; link to notebooks: ' + ', '.join(retired_guides(root))
    lines = (root / 'myst.yml').read_text().splitlines()
    for i, line in enumerate(lines[:-1]):
        if '- file: notebooks/chapters/' in line:
            assert not lines[i+1].strip().startswith('children:'), 'A chapter notebook must be a leaf page'
    reader_pages = check_reader_pages(root, toc)
    chapters = sorted((root / 'notebooks/chapters').glob('*.ipynb'))
    assert [int(p.name[:2]) for p in chapters] == list(range(1,16)), 'Expected chapters 1..15'
    for p in [root/'notebooks/quickstart.ipynb', *chapters]:
        assert p.relative_to(root).as_posix() in toc
        nb = json.loads(p.read_text())
        assert sum('validation_scope' in c.get('metadata',{}).get('tags',[]) for c in nb['cells']) == 1, p
        if p in chapters:
            assert ''.join(nb['cells'][0]['source']).startswith(f'# {int(p.name[:2])}장.'), p
        if p.name == '01_concepts.ipynb':
            assert not any(set(c.get('metadata', {}).get('tags', [])) &
                           {'requires_api', 'api_preparation', 'live_configuration'} for c in nb['cells']), \
                'Chapter 1 must remain a local concept walkthrough'
        for c in nb['cells']:
            if c['cell_type'] != 'code':continue
            assert not c.get('outputs') and c.get('execution_count') is None, p
            for node in ast.walk(ast.parse(''.join(c['source']))):
                if isinstance(node,ast.Assign) and any(isinstance(t,ast.Name) and t.id in {'RUN_LIVE','RUN_DOCKER'} for t in node.targets):
                    assert isinstance(node.value,ast.Constant) and node.value.value is False, p
    setup = json.loads((root / 'notebooks/setup.ipynb').read_text())
    assert not any(set(c.get('metadata', {}).get('tags', [])) &
                   {'requires_api', 'api_preparation', 'live_configuration'} for c in setup['cells']), \
        'Setup must remain local without API preparation'
    for c in setup['cells']:
        if c['cell_type'] == 'code':
            for node in ast.walk(ast.parse(''.join(c['source']))):
                if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'RUN_LIVE' for t in node.targets):
                    raise AssertionError('Setup has no live-execution switch')
    broken=[]
    files=[root/'README.md',root/'index.md',*list((root/'docs').rglob('*.md')),*list((root/'notebooks').rglob('*.ipynb'))]
    for p in files:
        if '.ipynb_checkpoints' in p.parts:continue
        body = chr(10).join(''.join(c['source']) for c in json.loads(p.read_text())['cells'] if c['cell_type']=='markdown') if p.suffix=='.ipynb' else p.read_text()
        body = re.sub(r'```.*?```','',body,flags=re.DOTALL)
        for target in re.findall(r'!?\[[^\]]*\]\(([^)]+)\)',body):
            target=target.strip().split(' "',1)[0].strip('<>')
            parsed=urlparse(target)
            if parsed.scheme or target.startswith(('#','/')):continue
            local=unquote(parsed.path)
            if local and not (p.parent/local).exists():broken.append(f'{p.relative_to(root)}: {local}')
    assert not broken,'Broken local links: '+'; '.join(broken)
    project=tomllib.loads((root/'pyproject.toml').read_text())
    lock=tomllib.loads((root/'uv.lock').read_text())
    urls=[i['url'] for i in project.get('tool',{}).get('uv',{}).get('index',[])]
    urls += [p['source']['registry'] for p in lock['package'] if 'registry' in p['source']]
    public_registry=bool(urls) and all(urlparse(u).hostname=='pypi.org' for u in urls)
    warnings=[]
    if not config['repository']:warnings.append('GitHub repository is not configured')
    if not public_registry:warnings.append('Public installation blocked: private registry remains; registry change needs explicit approval')
    return {'toc_entries':len(toc),'reader_documents':reader_pages,'internal_documents_excluded':True,'notebook_first':True,'chapters':15,'local_links_valid':True,'default_off':True,
            'repository_configured':bool(config['repository']),'public_registry':public_registry,'warnings':warnings}

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--require-public',action='store_true')
    parser.add_argument('--require-repository',action='store_true')
    args=parser.parse_args();report=check()
    print(json.dumps(report,ensure_ascii=False,indent=2))
    if (args.require_public and not report['public_registry']) or (args.require_repository and not report['repository_configured']):raise SystemExit(1)

if __name__=='__main__':main()
