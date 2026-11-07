"""Validated translation catalogs; never modify maintained notebooks or call an API."""
from __future__ import annotations
import copy
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def pages(root=ROOT):
    return re.findall(r'^ *- file: (.+)$', (Path(root) / 'myst.yml').read_text(), re.M)


def units(root, source):
    path = Path(root) / source
    if path.suffix == '.ipynb':
        return {c['id']: ''.join(c['source']) for c in json.loads(path.read_text())['cells']
                if c['cell_type'] == 'markdown'}
    if source == 'myst.yml':
        values = re.findall(r'^\s*(?:- )?(?:title|description|logo_text): (.+)$', path.read_text(), re.M)
        return {'text-' + sha(v)[:16]: v for v in values}
    return {'document': path.read_text()}


def catalog_path(root, source):
    return Path(root) / 'translations/en' / (source + '.json')


def protect(text):
    """Protect executable examples, identifiers, URLs and MyST syntax during translation."""
    spans = []
    def save(match):
        spans.append(match.group())
        return f'⟦P{len(spans)-1}⟧'
    pattern = r'(?ms)^```[^\n]*\n.*?^```[^\n]*$|^~~~[^\n]*\n.*?^~~~[^\n]*$|<!--.*?-->|`[^`\n]+`|https?://[^\s)<>]+|(?<=\]\()[^\s)]+|^\([\w-]+\)='
    return re.sub(pattern, save, text), spans


def restore(text, spans):
    expected = [f'⟦P{i}⟧' for i in range(len(spans))]
    found = re.findall(r'⟦P\d+⟧', text)
    if sorted(found) != sorted(expected):
        raise ValueError('Translation changed protected Markdown tokens')
    for key, value in zip(expected, spans):
        text = text.replace(key, value)
    return text


def validate_translation(source, translated):
    if source.strip() and not translated.strip():
        raise ValueError('Translation text is empty')
    _, before = protect(source)
    _, after = protect(translated)
    if Counter(before) != Counter(after):
        raise ValueError('Translation changed code, inline literals, links or directives')
    fences = lambda spans: [s for s in spans if s.startswith(('```','~~~'))]
    if fences(before) != fences(after):
        raise ValueError('Translation reordered executable code examples')
    def headings(value):
        protected, _ = protect(value)
        return re.findall(r'^(#{1,6}) ', protected, re.M)
    if headings(source) != headings(translated):
        raise ValueError('Translation changed heading structure')
    if re.search('[가-힣]', protect(translated)[0]):
        raise ValueError('Untranslated Korean prose remains')


def entries(root, source):
    current = units(root, source)
    path = catalog_path(root, source)
    if not path.is_file():
        raise ValueError('Missing translation: ' + source)
    data = json.loads(path.read_text())
    if data.get('source') != source or set(data['units']) != set(current):
        raise ValueError('Translation unit set changed: ' + source)
    glossary = sha((Path(root) / 'translations/glossary.json').read_text())
    if data.get('glossary_sha256') != glossary:
        raise ValueError('Translation glossary changed: ' + source)
    for key, value in current.items():
        item = data['units'][key]
        if item['source_sha256'] != sha(value):
            raise ValueError(f'Stale translation: {source}:{key}')
        validate_translation(value, item['text'])
    return {key: item['text'] for key, item in data['units'].items()}


def check(root=ROOT):
    count = 0
    for source in [*pages(root), 'myst.yml']:
        count += len(entries(root, source))
    registry = json.loads((Path(root) / 'translations/pages.json').read_text())
    if set(registry) != set(pages(root)) or len(set(registry.values())) != len(registry):
        raise ValueError('Invalid language-neutral page registry')
    return {'languages': ['ko', 'en'], 'pages': len(registry), 'translation_units': count}


def notebook(root, source, language='ko'):
    original = json.loads((Path(root) / source).read_text())
    result = copy.deepcopy(original)
    if language == 'en':
        text = entries(root, source)
        for cell in result['cells']:
            if cell['cell_type'] == 'markdown':
                cell['source'] = text[cell['id']].splitlines(keepends=True)
        first = next(c for c in result['cells'] if c['cell_type'] == 'markdown')
        first['source'] = (''.join(first['source']).rstrip() + '\n\n> The executable code is identical to the Korean source. Examples that request Korean reports continue to generate Korean reports.\n').splitlines(keepends=True)
    elif language != 'ko':
        raise ValueError('Unsupported language')
    return result


def materialize(root, destination):
    """Overlay English text onto an isolated copy, keeping every code cell intact."""
    root, destination = Path(root), Path(destination)
    check(root)
    for source in pages(root):
        path = destination / source
        if path.suffix == '.ipynb':
            path.write_text(json.dumps(notebook(root, source, 'en'), ensure_ascii=False, indent=1) + '\n')
        else:
            path.write_text(entries(root, source)['document'])
    config = destination / 'myst.yml'
    replacements = entries(root, 'myst.yml')
    def title(match):
        return match[1] + json.dumps(replacements['text-' + sha(match[2])[:16]], ensure_ascii=False)
    config.write_text(re.sub(r'^(\s*(?:- )?(?:title|description|logo_text): )(.+)$', title, config.read_text(), flags=re.M))


if __name__ == '__main__':
    print(json.dumps(check()))
