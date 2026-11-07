"""Publication regressions: no real GitHub or Colab calls."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from configure_repository import render_updates
from pages_base_url import pages_base_url
from check_tutorial import check

@contextlib.contextmanager
def fixture():
    with tempfile.TemporaryDirectory() as temporary:
        root=Path(temporary)
        for name in ['README.md','index.md','myst.yml','tutorial.json','pyproject.toml','uv.lock','book-redirects.json','.env.example']:
            shutil.copyfile(ROOT/name,root/name)
        for name in ['notebooks','docs','data','src','translations']:
            shutil.copytree(ROOT/name,root/name,ignore=shutil.ignore_patterns('.ipynb_checkpoints'))
        yield root

class PublicationTests(unittest.TestCase):
    def test_current_repository_links_and_independent_notice(self):
        from build_colab import render
        config = json.loads((ROOT / 'tutorial.json').read_text())
        repository = config['repository']
        owner = repository.split('/')[0]
        readme = (ROOT / 'README.md').read_text()
        self.assertIn('git clone https://github.com/' + repository + '.git', readme)
        self.assertIn('https://' + owner + '.github.io' + pages_base_url(repository) + '/', readme)
        notice = '이 프로젝트는 OpenAI가 공식 제작하거나 승인한 문서가 아닌 독립적인 학습 자료입니다.'
        self.assertIn(notice, readme)
        self.assertIn(notice, (ROOT / 'index.md').read_text())
        self.assertIn(notice, render()[ROOT / '_build/colab/README.md'])

    def test_pages_root_requires_matching_owner(self):
        self.assertEqual(pages_base_url('Owner/owner.github.io'),'')
        self.assertEqual(pages_base_url('owner/agents-api-by-example'),'/agents-api-by-example')
        self.assertEqual(pages_base_url('owner/other.github.io'),'/other.github.io')

    def test_pages_rejects_invalid_repository_input(self):
        for repository in ['https://github.com/owner/repo','owner/repo;command','owner/repo extra']:
            with self.assertRaises(ValueError):pages_base_url(repository)

    def test_colab_guide_is_independent_of_repository_ref(self):
        with fixture() as root:
            updates=render_updates(root,'demo/tutorial','release/v1')
            ordinary=json.loads(updates[root/'notebooks/chapters/07_function_tools.ipynb'])
            docker=json.loads(updates[root/'notebooks/chapters/12_self_hosted.ipynb'])
            def marker(nb):
                return next(''.join(c['source']) for c in nb['cells'] if ''.join(c['source']).startswith('<!-- colab-link -->'))
            self.assertIn('Colab 업로드용',marker(ordinary))
            self.assertIn('실습은 로컬 Docker',marker(docker))
            self.assertIn('../../docs/colab.md',marker(ordinary))
            self.assertNotIn('colab.research.google.com/github',marker(ordinary))
            for p,body in updates.items():p.write_text(body)
            self.assertTrue(all(p.read_text()==body for p,body in render_updates(root,'demo/tutorial','release/v1').items()))
            self.assertEqual(json.loads((root/'tutorial.json').read_text())['repository'],'demo/tutorial')
            self.assertEqual(json.loads((root/'tutorial.json').read_text())['ref'],'release/v1')

    def test_bootstraps_skip_colab_installs_during_offline_check(self):
        paths=[ROOT/'notebooks/setup.ipynb',ROOT/'notebooks/quickstart.ipynb',ROOT/'notebooks/chapters/07_function_tools.ipynb']
        for path in paths:
            nb=json.loads(path.read_text())
            cell=next(c for c in nb['cells'] if 'bootstrap' in c.get('metadata',{}).get('tags',[]))
            with patch.dict(os.environ,{'TUTORIAL_OFFLINE_CHECK':'1'}), patch('importlib.util.find_spec',return_value=object()), patch('subprocess.run') as run,contextlib.redirect_stdout(io.StringIO()):
                exec(compile(''.join(cell['source']),str(path),'exec'),{'__name__':'offline_bootstrap_test'})
                run.assert_not_called()

    def test_catalog_rejects_enabled_paid_switch(self):
        with fixture() as root:
            path=root/'notebooks/chapters/02_first_agent.ipynb'
            nb=json.loads(path.read_text())
            for cell in nb['cells']:
                if cell['cell_type']=='code':
                    cell['source']=''.join(cell['source']).replace('RUN_LIVE = False','RUN_LIVE = True').splitlines(keepends=True)
            path.write_text(json.dumps(nb))
            with self.assertRaises(AssertionError):check(root)

    def test_catalog_rejects_missing_toc_document(self):
        with fixture() as root:
            p=root/'myst.yml';p.write_text(p.read_text().replace('file: index.md','file: does-not-exist.md'))
            with self.assertRaisesRegex(AssertionError,'missing file'):check(root)

    def test_repository_check_failure_prevents_artifact_generation(self):
        from build_artifacts import build
        with fixture() as root, patch.dict(os.environ, {'GITHUB_REPOSITORY':'other/repository'}):
            with patch('build_artifacts.build_colab') as generate:
                with self.assertRaisesRegex(ValueError, 'must match'):
                    build(root, 'pages')
                generate.assert_not_called()

    def test_workflows_fail_before_install_and_publish_main_only(self):
        import yaml
        for name in ['validate.yml','publish.yml']:
            workflow=yaml.load((ROOT/'.github/workflows'/name).read_text(),Loader=yaml.BaseLoader)
            self.assertIn('on',workflow)
            for job in workflow['jobs'].values():
                runs=[step.get('run','') for step in job.get('steps',[])]
                if 'uv sync --locked --group dev --group docs' in runs:
                    self.assertLess(next(i for i,r in enumerate(runs) if 'check_tutorial.py --require-public' in r),runs.index('uv sync --locked --group dev --group docs'))
        publish=yaml.load((ROOT/'.github/workflows/publish.yml').read_text(),Loader=yaml.BaseLoader)
        self.assertEqual(publish['jobs']['build']['if'],"github.ref == 'refs/heads/main'")
        self.assertEqual(publish['jobs']['deploy']['permissions'],{'pages':'write','id-token':'write'})

if __name__=='__main__':unittest.main()
