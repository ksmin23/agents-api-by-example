"""Artifact lifecycle regressions; no model, Docker or hosted deployment calls."""
import contextlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
from artifact_common import digest, source_state, tree
from build_bundles import build as bundles
from build_colab import build as colab
from build_colab_zip import build as package
from book_colab_downloads import add_downloads
from check_artifacts import check
from prepare_sites import prepare
from test_publication import fixture


@contextlib.contextmanager
def artifacts():
    with fixture() as root:
        for folder in ['examples','skills','plugins','deploy','scripts','.github']:
            shutil.copytree(ROOT/folder,root/folder,ignore=shutil.ignore_patterns('.generated','__pycache__'))
        colab(root);bundles(root);package(root)
        html=root/'_build/book/sites'
        html.mkdir(parents=True);(html/'index.html').write_text('validated fixture')
        add_downloads(html,root)
        manifest={'schema_version':1,'source':source_state(root),'pages_base_url':'/agents-api-by-example',
                  'components':{name:{'directory':directory,'files':tree(root/directory)}
                                for name,directory in [('colab','_build/colab'),('bundles','_build/bundles')]},
                  'packages':{'colab-notebooks.zip':digest((root/'_build/packages/colab-notebooks.zip').read_bytes())},
                  'targets':{'sites':{'directory':'_build/book/sites','base_url':'','files':tree(html)}}}
        (root/'_build/manifest.json').write_text(json.dumps(manifest))
        yield root


class ArtifactTests(unittest.TestCase):
    def test_bundles_and_zip_are_independent_of_html_and_checks_do_not_write(self):
        with artifacts() as root:
            shutil.rmtree(root/'_build/book')
            before=tree(root)
            bundles(root,check=True);package(root,check=True)
            self.assertEqual(before,tree(root))
            archive=root/'_build/bundles/csv-report.zip'
            archive.write_bytes(b'corrupt')
            with self.assertRaisesRegex(ValueError,'stale'):
                bundles(root,check=True)
            self.assertEqual(archive.read_bytes(),b'corrupt')

    def test_unexpected_bundle_file_is_rejected(self):
        with artifacts() as root:
            (root/'plugins/sales-reporting/secret.txt').write_text('excluded')
            with self.assertRaisesRegex(ValueError, 'Unexpected bundle file type'):
                bundles(root)

    def test_bundle_format_matches_existing_skill_and_plugin_examples(self):
        from tutorial_helpers.extensions import archive_folder
        with artifacts() as root:
            for folder in ['skills/csv-report','plugins/sales-reporting']:
                path=root/folder
                self.assertEqual((root/'_build/bundles'/(path.name+'.zip')).read_bytes(),archive_folder(path))

    def test_manifest_check_is_read_only_and_detects_input_and_output_changes(self):
        with artifacts() as root:
            before=tree(root)
            self.assertTrue(check(root)['read_only'])
            self.assertEqual(before,tree(root))
            (root/'data/sales.csv').write_text('changed')
            with self.assertRaisesRegex(AssertionError,'inputs changed'):
                check(root)
        with artifacts() as root:
            (root/'_build/book/sites/index.html').write_text('tampered')
            with self.assertRaisesRegex(AssertionError,'tree changed'):
                check(root)

    def test_source_manifest_excludes_builds_and_append_only_run_records(self):
        with artifacts() as root:
            before=source_state(root)['files']
            (root/'.work/archive').mkdir(parents=True)
            (root/'.work/PROGRESS.md').write_text('completion record')
            (root/'.work/archive/plan.md').write_text('local plan')
            (root/'PROGRESS.md').write_text('legacy completion record')
            (root/'todo.md').write_text('legacy todo')
            (root/'docs/tutorial-improvement-plan.md').write_text('legacy plan')
            (root/'outputs').mkdir();(root/'outputs/runtime.json').write_text('runtime')
            self.assertEqual(before,source_state(root)['files'])

    def test_sites_preparation_preserves_identity_and_never_publishes(self):
        with artifacts() as root, tempfile.TemporaryDirectory() as folder:
            checkout=Path(folder)
            (checkout/'.openai').mkdir()
            hosting=checkout/'.openai/hosting.json'
            hosting.write_text(json.dumps({'project_id':'fixture-only','static':{'directory':'dist'}}))
            subprocess.run(['git','init','-q',str(checkout)],check=True)
            subprocess.run(['git','-C',str(checkout),'add','.'],check=True)
            subprocess.run(['git','-C',str(checkout),'-c','user.name=Fixture','-c','user.email=fixture@example.test','commit','-qm','fixture'],check=True)
            identity=hosting.read_bytes()
            (root/'.work').mkdir()
            (root/'.work/PROGRESS.md').write_text('local run history')
            (root/'docs/tutorial-improvement-validation.md').write_text('legacy run history')
            result=prepare(checkout,root)
            self.assertFalse(result['published'])
            self.assertFalse((checkout/'book-source/.work').exists())
            self.assertFalse((checkout/'book-source/docs/tutorial-improvement-validation.md').exists())
            self.assertEqual(hosting.read_bytes(),identity)
            self.assertEqual(tree(checkout/'dist'),tree(root/'_build/book/sites'))
            self.assertFalse((root/'_build/packages/sites.tar.gz').exists())
            before=tree(checkout)
            self.assertTrue(prepare(checkout,root,check=True)['read_only'])
            self.assertEqual(before,tree(checkout))
            with self.assertRaisesRegex(ValueError,'pending changes'):
                prepare(checkout,root)

    def test_incomplete_or_wrong_target_manifest_fails_closed(self):
        with artifacts() as root:
            with self.assertRaises(KeyError):
                check(root,'pages')
            manifest=root/'_build/manifest.json'
            data=json.loads(manifest.read_text());data['targets']['sites']['base_url']='/wrong'
            manifest.write_text(json.dumps(data))
            with self.assertRaises(AssertionError):
                check(root)


if __name__=='__main__':unittest.main()
