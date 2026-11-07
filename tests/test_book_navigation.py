"""Regressions for a single learner page per chapter and safe legacy URL handling."""
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from book_redirects import build_redirects
from check_tutorial import check
from check_book_output import check_output
from test_publication import fixture


class BookNavigationTests(unittest.TestCase):
    def test_duplicate_explanation_pages_cannot_return_to_the_toc(self):
        with fixture() as root:
            self.assertTrue(check(root)["notebook_first"])
            legacy = root / "docs/intro/01_concepts.md"
            legacy.parent.mkdir(parents=True, exist_ok=True)
            legacy.write_text("# Retired explanation")
            path = root / "myst.yml"
            path.write_text(path.read_text().replace(
                "- file: notebooks/chapters/01_concepts.ipynb",
                "- file: docs/intro/01_concepts.md\n          children:\n            - file: notebooks/chapters/01_concepts.ipynb",
            ))
            with self.assertRaisesRegex(AssertionError, "canonical"):
                check(root)

    def test_retired_guides_cannot_return_even_outside_the_toc(self):
        names = ['docs/chapters/02_sessions.md', 'docs/intro/01_concepts.md',
                 'docs/deployment/12_self_hosted.md', 'docs/extensions/07_function_tools.md',
                 'docs/getting-started.md', 'docs/architecture.md']
        for name in names:
            with self.subTest(name=name), fixture() as root:
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text('# Retired guide')
                with self.assertRaisesRegex(AssertionError, 'Retired guide'):
                    check(root)

    def test_link_to_a_removed_document_is_rejected(self):
        with fixture() as root:
            path = root / 'index.md'
            path.write_text(path.read_text() + '\n[Old explanation](docs/intro/01_concepts.md)\n')
            with self.assertRaisesRegex(AssertionError, 'Missing local document'):
                check(root)

    def test_all_legacy_routes_work_without_markdown_guides(self):
        mapping = json.loads((ROOT / 'book-redirects.json').read_text())
        self.assertEqual(len(mapping), 16)
        for base in ['', '/agents-api-by-example']:
            with self.subTest(base=base), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                for target in set(mapping.values()):
                    path = root / target / 'index.html'
                    path.parent.mkdir(parents=True)
                    path.write_text('canonical notebook page')
                self.assertEqual(build_redirects(root, mapping=mapping, base_url=base)['compatibility_pages'], 16)
                for old, target in mapping.items():
                    body = (root / old / 'index.html').read_text()
                    self.assertIn('content="0;url=' + base + '/' + target + '/', body)
                    self.assertIn('location.search + location.hash', body)
                    self.assertEqual((root / target / 'index.html').read_text(), 'canonical notebook page')

    def test_every_chapter_retains_an_integrated_learning_overview(self):
        paths = sorted((ROOT / "notebooks/chapters").glob("*.ipynb"))
        self.assertEqual(len(paths), 15)
        for path in paths:
            notebook = json.loads(path.read_text())
            self.assertTrue(notebook["metadata"]["tutorial"]["integrated_documents"], path)
            overviews = [c for c in notebook["cells"] if "chapter_overview" in c["metadata"].get("tags", [])]
            self.assertEqual(len(overviews), 1, path)
            self.assertTrue("".join(overviews[0]["source"]).startswith("## 학습 안내"))

    def test_work_records_are_rejected_as_menu_pages(self):
        for name in ["PROGRESS.md", "todo.md", "docs/tutorial-improvement-validation.md"]:
            with self.subTest(name=name), fixture() as root:
                (root / name).parent.mkdir(parents=True, exist_ok=True)
                (root / name).write_text("Local work record")
                path = root / "myst.yml"
                path.write_text(path.read_text().replace("\nsite:", "\n    - file: " + name + "\nsite:"))
                with self.assertRaisesRegex(AssertionError, "Repository-only"):
                    check(root)

    def test_hidden_work_record_link_in_a_notebook_is_rejected(self):
        with fixture() as root:
            (root / "PROGRESS.md").write_text("Local work record")
            path = root / "notebooks/chapters/07_function_tools.ipynb"
            notebook = json.loads(path.read_text())
            notebook["cells"][0]["source"].append("\n[작업 기록](../../PROGRESS.md)\n")
            path.write_text(json.dumps(notebook))
            with self.assertRaisesRegex(AssertionError, "Repository-only"):
                check(root)

    def test_hashed_work_record_download_is_rejected_from_static_output(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "index.html").write_text("book")
            self.assertEqual(check_output(root)["internal_documents_exported"], 0)
            (root / "_static").mkdir()
            (root / "_static/PROGRESS-oldhash.md").write_text("old working notes")
            with self.assertRaisesRegex(AssertionError, "Repository-only"):
                check_output(root)

    def test_legacy_url_supports_project_base_url_and_is_idempotent(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "concepts").mkdir()
            (root / "concepts/index.html").write_text("canonical")
            mapping = {"concepts-1": "concepts"}
            expected = build_redirects(root, mapping=mapping, base_url="/guide")
            self.assertEqual(expected, build_redirects(root, mapping=mapping, base_url="/guide"))
            output = (root / "concepts-1/index.html").read_text()
            self.assertIn('/guide/concepts/', output)
            self.assertEqual((root / "concepts/index.html").read_text(), "canonical")

    def test_compatibility_generation_cannot_overwrite_content(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            for name in ["old", "new"]:
                (root / name).mkdir(); (root / name / "index.html").write_text(name)
            with self.assertRaisesRegex(ValueError, "overwrite"):
                build_redirects(root, mapping={"old": "new"})
            self.assertEqual((root / "old/index.html").read_text(), "old")

    def test_missing_target_or_unsafe_route_does_not_create_partial_redirects(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); (root / "new").mkdir(); (root / "new/index.html").write_text("new")
            with self.assertRaisesRegex(ValueError, "Missing"):
                build_redirects(root, mapping={"old": "new", "another": "missing"})
            self.assertFalse((root / "old").exists())
            with self.assertRaisesRegex(ValueError, "simple"):
                build_redirects(root, mapping={"../outside": "new"})


if __name__ == "__main__":
    unittest.main()
