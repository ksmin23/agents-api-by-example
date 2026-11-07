"""Join language builds, add alternate links, and validate route/anchor pairs."""
from __future__ import annotations
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import shutil
from urllib.parse import unquote, urljoin, urlsplit
from localization import ROOT


def headings(node):
    if isinstance(node, dict):
        if node.get('type') == 'heading':
            yield (node['depth'], node.get('html_id',node.get('identifier')))
        for value in node.get('children', []):
            yield from headings(value)
    elif isinstance(node,list):
        for value in node:yield from headings(value)


class ReaderLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.urls = []

    def handle_starttag(self, tag, attrs):
        attributes = dict(attrs)
        key = 'href' if tag == 'a' else 'src' if tag == 'script' else None
        if key and attributes.get(key):
            self.urls.append(attributes[key])


def check_local_links(path, directory, base):
    parser = ReaderLinks()
    parser.feed(path.read_text())
    current = 'https://tutorial.invalid' + base + '/' + path.relative_to(directory).as_posix()
    for url in parser.urls:
        resolved = urlsplit(urljoin(current, url))
        if resolved.netloc != 'tutorial.invalid' or resolved.scheme not in ['http', 'https']:
            continue
        pathname = unquote(resolved.path)
        assert pathname.startswith(base + '/'), f'Link escaped deployment base: {path}: {url}'
        target = directory / pathname[len(base) + 1:]
        if target.is_dir():
            target /= 'index.html'
        assert target.is_file(), f'Missing local link target: {path}: {url}'
    return len(parser.urls)


def assemble(directory, base='', root=ROOT):
    directory, root = Path(directory),Path(root)
    registry = json.loads((root/'translations/pages.json').read_text())
    mapping={'base_url':base,'pages':registry,'anchors':{}}
    for slug in registry.values():
        pair=[]
        for language in ['ko','en']:
            path=directory/('en' if language=='en' else '')/(slug+'.json')
            page=json.loads(path.read_text())
            assert page['slug']==slug, 'Translated title changed the page URL: '+slug
            pair.append(list(headings(page['mdast'])))
            identifiers = [identifier for _, identifier in pair[-1]]
            assert all(isinstance(value, str) and value for value in identifiers)
            assert len(set(identifiers)) == len(identifiers), 'Duplicate heading anchors: ' + slug
        assert [a[0] for a in pair[0]]==[a[0] for a in pair[1]], 'Heading structure differs: '+slug
        mapping['anchors'][slug]={
            'ko':{a[1]:b[1] for a,b in zip(*pair)},
            'en':{b[1]:a[1] for a,b in zip(*pair)},
        }
    (directory/'language-map.json').write_text(json.dumps(mapping,ensure_ascii=False,indent=2)+'\n')
    shutil.copy2(root/'scripts/language_switch.mjs',directory/'language-switch.mjs')
    for path in directory.rglob('*.html'):
        relative=path.relative_to(directory)
        language='en' if relative.parts[0]=='en' else 'ko'
        content=path.read_text()
        if 'tutorial-redirect' in content:
            continue
        route=relative.as_posix()
        if route.startswith('en/'):route=route[3:]
        route=route.removesuffix('index.html')
        prefix=base+'/' if base else '/'
        ko=prefix+route;en=prefix+'en/'+route
        addition=(f'<meta name="tutorial-language" content="{language}">'
                  f'<meta name="tutorial-base" content="{base}">'
                  f'<link rel="alternate" hreflang="ko" href="{ko}">'
                  f'<link rel="alternate" hreflang="en" href="{en}">'
                  f'<script type="module" src="{prefix}language-switch.mjs"></script>')
        content=re.sub(r'<html\b[^>]*>',lambda m:re.sub(r'lang="[^"]*"',f'lang="{language}"',m.group()),content,count=1)
        content=content.replace('</head>',addition+'</head>',1)
        path.write_text(content)
    return check(directory,base,root)


def check(directory,base='',root=ROOT):
    directory,root=Path(directory),Path(root)
    mapping=json.loads((directory/'language-map.json').read_text())
    registry=json.loads((root/'translations/pages.json').read_text())
    assert mapping['pages']==registry and mapping['base_url']==base
    links_checked = 0
    for language in ['ko','en']:
        folder=directory/('en' if language=='en' else '')
        config=json.loads((folder/'config.json').read_text())
        actual={p['slug'] for p in config['projects'][0]['pages'] if 'slug' in p}|{'index'}
        assert actual==set(registry.values()), 'Language page set differs'
        assert (folder/'myst.search.json').is_file()
        for slug in registry.values():
            path=folder/('index.html' if slug=='index' else slug+'/index.html')
            text=path.read_text()
            links_checked += check_local_links(path, directory, base)
            assert re.search(r'<html\b[^>]*lang="' + language + '"', text)
            assert f'name="tutorial-language" content="{language}"' in text
            assert f'src="{base}/language-switch.mjs"' in text
            for locale in ['ko','en']:
                url=(base+'/' if base else '/')+('en/' if locale=='en' else '')+('' if slug=='index' else slug+'/')
                assert f'hreflang="{locale}" href="{url}"' in text
    return {'languages':['ko','en'],'reader_pages_per_language':len(registry),
            'language_links_verified':True, 'reader_links_checked': links_checked}
