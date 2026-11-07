"""Fresh translations, immutable examples and target-aware language navigation."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from localization import catalog_path, entries, notebook, protect, restore, validate_translation
from build_colab import render
from book_languages import assemble, check, check_local_links
from test_publication import fixture


class LocalizationTests(unittest.TestCase):
    def test_protected_examples_and_links_cannot_change(self):
        source='## 준비\n\nRun `client.beta.agents` at [docs](https://example.test/a#b).\n```python\nprint(42)\n```\n'
        masked,spans=protect(source)
        translated=restore(masked.replace('준비','Preparation'),spans)
        validate_translation(source,translated)
        with self.assertRaises(ValueError):
            restore(masked.replace('⟦P0⟧',''),spans)
        with self.assertRaises(ValueError):
            validate_translation(source,translated.replace('print(42)','print(43)'))
        with self.assertRaises(ValueError):
            validate_translation(source,translated.replace('## Preparation','# Preparation'))
        with self.assertRaisesRegex(ValueError, 'empty'):
            validate_translation('설명', '')

    def test_missing_and_stale_translation_are_rejected(self):
        with fixture() as root:
            path=catalog_path(root,'index.md')
            path.unlink()
            with self.assertRaisesRegex(ValueError,'Missing translation'):
                entries(root,'index.md')
        with fixture() as root:
            (root/'index.md').write_text('Changed source')
            with self.assertRaisesRegex(ValueError,'Stale translation'):
                entries(root,'index.md')
        with fixture() as root:
            (root/'translations/glossary.json').write_text('{}')
            with self.assertRaisesRegex(ValueError,'glossary changed'):
                entries(root,'index.md')

    def test_english_notebooks_and_colab_preserve_all_code_and_source_bytes(self):
        before={p:p.read_bytes() for p in (ROOT/'notebooks').rglob('*.ipynb') if '.ipynb_checkpoints' not in p.parts}
        exported=render(ROOT,'en')
        self.assertEqual(sum(p.suffix=='.ipynb' for p in exported),17)
        for path,text in exported.items():
            if path.suffix!='.ipynb':continue
            en=json.loads(text)
            source=json.loads((ROOT/en['metadata']['tutorial']['source']).read_text())
            translated = notebook(ROOT, en['metadata']['tutorial']['source'], 'en')
            self.assertEqual(source['metadata'], translated['metadata'])
            self.assertEqual([c for c in source['cells'] if c['cell_type']=='code'],
                             [c for c in translated['cells'] if c['cell_type']=='code'])
            code={c['id']:c['source'] for c in source['cells'] if c['cell_type']=='code' and 'bootstrap' not in c['metadata'].get('tags',[])}
            self.assertEqual(code,{c['id']:c['source'] for c in en['cells'] if c['id'] in code})
            self.assertEqual(source['metadata']['kernelspec'],en['metadata']['kernelspec'])
        self.assertEqual(before,{p:p.read_bytes() for p in before})

    def test_language_paths_handle_pages_prefix_without_double_en(self):
        module=(ROOT/'scripts/language_switch.mjs').as_uri()
        script=f"import {{languagePath}} from {json.dumps(module)}; console.log(JSON.stringify([languagePath('/multi-agent/','','en'),languagePath('/en/multi-agent/','','ko'),languagePath('/guide/multi-agent/','/guide','en'),languagePath('/guide/en/multi-agent/','/guide','ko')]));"
        result=subprocess.check_output(['node','--input-type=module','-e',script],text=True)
        self.assertEqual(json.loads(result),['/en/multi-agent/','/multi-agent/','/guide/en/multi-agent/','/guide/multi-agent/'])

    def test_assembled_pages_have_language_links_and_paired_heading_anchors(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);(root/'translations').mkdir();(root/'scripts').mkdir()
            (root/'translations/pages.json').write_text(json.dumps({'index.md':'index','notebook.ipynb':'lesson'}))
            shutil.copy2(ROOT/'scripts/language_switch.mjs',root/'scripts/language_switch.mjs')
            output=root/'book'
            for lang in ['ko','en']:
                folder=output/('en' if lang=='en' else '');folder.mkdir(parents=True,exist_ok=True)
                (folder/'config.json').write_text(json.dumps({'projects':[{'pages':[{'slug':'lesson'}]}]}))
                (folder/'myst.search.json').write_text('{}')
                for slug in ['index','lesson']:
                    (folder/(slug+'.json')).write_text(json.dumps({'slug':slug,'mdast':{'type':'root','children':[{'type':'heading','depth':2,'html_id':lang+'-section'}]}}))
                    p=folder/('index.html' if slug=='index' else slug+'/index.html');p.parent.mkdir(exist_ok=True)
                    p.write_text('<html lang="en"><head></head><body>Content</body></html>')
            result=assemble(output,'/guide',root)
            self.assertTrue(result['language_links_verified'])
            mapping=json.loads((output/'language-map.json').read_text())
            self.assertEqual(mapping['anchors']['lesson']['ko']['ko-section'],'en-section')
            self.assertIn('hreflang="en" href="/guide/en/lesson/"',(output/'lesson/index.html').read_text())
            (output/'en/lesson/index.html').unlink()
            with self.assertRaises(FileNotFoundError):check(output,'/guide',root)

    def test_missing_links_and_incorrect_pages_prefix_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            path = root/'index.html'
            path.write_text('<a href="/guide/missing/">Missing</a>')
            with self.assertRaisesRegex(AssertionError, 'Missing local link'):
                check_local_links(path, root, '/guide')
            path.write_text('<a href="/en/">Incorrect Pages base</a>')
            with self.assertRaisesRegex(AssertionError, 'escaped deployment base'):
                check_local_links(path, root, '/guide')


if __name__=='__main__':unittest.main()
