"""Fresh checkouts must not require author-specific work records."""
import sys
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from update_intro_progress import update
from artifact_common import source_state


class WorkRecordTests(unittest.TestCase):
    def test_first_update_creates_unverified_local_table_and_preserves_other_rows(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            before = source_state(root)['files']
            update(12, offline='Passed', note='Offline fixture only.', root=root)
            progress = root / '.work/PROGRESS.md'
            text = progress.read_text()
            self.assertIn('| 12 | Chapter 12 | Not recorded | Passed | Not run |', text)
            self.assertIn('| 13 | Chapter 13 | Not recorded | Not run | Not run |', text)
            self.assertIn('Offline fixture only.', text)
            update(12, live='Failed', note='Live fixture only.', root=root)
            self.assertIn('| 12 | Chapter 12 | Not recorded | Passed | Failed |', progress.read_text())
            self.assertIn('Offline fixture only.', progress.read_text())
            self.assertEqual(before, source_state(root)['files'])
            self.assertFalse((root / 'PROGRESS.md').exists())

    def test_existing_local_history_is_preserved(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            (root / '.work').mkdir()
            progress = root / '.work/PROGRESS.md'
            progress.write_text('# Prior history\n| 7 | Tools | Draft | Not run | Not run |\n')
            update(7, writing='Complete', note='Updated.', root=root)
            self.assertTrue(progress.read_text().startswith('# Prior history\n'))
            self.assertIn('| 7 | Tools | Complete | Not run | Not run |', progress.read_text())


if __name__ == '__main__':
    unittest.main()
