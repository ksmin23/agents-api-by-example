"""Exercise standalone setup without credentials, GitHub or package installation."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from build_colab import build, installer, render
from check_colab import check_exports


class ColabSetupTests(unittest.TestCase):
    def test_local_bootstrap_never_installs(self):
        nb=json.loads((ROOT / "notebooks/quickstart.ipynb").read_text())
        source=next("".join(c["source"]) for c in nb["cells"] if "bootstrap" in c["metadata"].get("tags", []))
        with patch.dict(sys.modules), patch("subprocess.run") as run:
            sys.modules.pop("google.colab", None)
            with contextlib.redirect_stdout(io.StringIO()):
                exec(source, {})
            run.assert_not_called()

    def test_standalone_installs_named_packages_in_current_python(self):
        with patch.dict(os.environ, {"TUTORIAL_OFFLINE_CHECK": "0"}), patch("subprocess.run") as run:
            exec(installer(["openai==3.42.1", "python-dotenv==1.2.4"]), {})
            command = run.call_args.args[0]
            self.assertEqual(command[:4], [sys.executable, "-m", "pip", "install"])
            self.assertEqual(command[-2:], ["openai==3.42.1", "python-dotenv==1.2.4"])
            self.assertNotIn("-r", command)
            self.assertTrue(run.call_args.kwargs["check"])

    def test_offline_standalone_does_not_install(self):
        with patch.dict(os.environ, {"TUTORIAL_OFFLINE_CHECK": "1"}), patch("subprocess.run") as run:
            with contextlib.redirect_stdout(io.StringIO()):
                exec(installer(["openai==3.42.1"]), {})
            run.assert_not_called()

    def test_skill_files_materialize_without_a_repository(self):
        exported = json.loads(render()[ROOT / "_build/colab/chapters/09_skills.ipynb"])
        old = Path.cwd()
        try:
            with tempfile.TemporaryDirectory() as folder:
                namespace = {"os": os, "sys": sys}
                before = list(sys.path)
                try:
                    with patch.dict(sys.modules), patch("tempfile.mkdtemp", return_value=folder), patch("urllib.request.urlopen", side_effect=AssertionError("No downloads")):
                        with contextlib.redirect_stdout(io.StringIO()):
                            for c in exported["cells"]:
                                if "colab_asset" in c["metadata"].get("tags", []):
                                    exec("".join(c["source"]), namespace)
                        self.assertEqual((Path(folder) / "skills/csv-report/SKILL.md").read_bytes(), (ROOT / "skills/csv-report/SKILL.md").read_bytes())
                        self.assertTrue((Path(folder) / "src/tutorial_helpers/common.py").is_file())
                finally:
                    sys.path[:] = before
                    os.chdir(old)
        finally:
            os.chdir(old)

    def test_exports_preserve_api_cells_and_are_in_sync(self):
        from test_publication import fixture
        import shutil
        with fixture() as root:
            for folder in ["examples", "skills", "plugins", "deploy"]:
                shutil.copytree(ROOT / folder, root / folder, ignore=shutil.ignore_patterns(".generated", "__pycache__"))
            build(root)
            self.assertEqual(len(check_exports(root)), 17)

    def test_build_never_changes_sources_and_detects_a_stale_export(self):
        from test_publication import fixture
        import hashlib
        import shutil
        with fixture() as root:
            for folder in ["examples", "skills", "plugins", "deploy"]:
                shutil.copytree(ROOT / folder, root / folder, ignore=shutil.ignore_patterns(".generated", "__pycache__"))
            # Deliberate formatting must survive; the builder must not normalize it.
            original = root / "notebooks/quickstart.ipynb"
            original.write_text(original.read_text() + "\n")
            def snapshot():
                return {p.relative_to(root).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest()
                        for p in root.rglob("*") if p.is_file() and "_build" not in p.relative_to(root).parts}
            before = snapshot()
            build(root)
            self.assertEqual(before, snapshot())
            self.assertTrue(all(p.is_relative_to(root / "_build/colab") for p in render(root)))
            build(root, check=True)
            self.assertEqual(before, snapshot())
            output = root / "_build/colab/quickstart.ipynb"
            self.assertEqual(json.loads(output.read_text())["metadata"]["tutorial"]["source_sha256"],
                             hashlib.sha256(original.read_bytes()).hexdigest())
            output.write_text(output.read_text() + "\n")
            with self.assertRaisesRegex(ValueError, "build_colab"):
                build(root, check=True)

    def test_ci_builds_then_checks_and_uploads_only_generated_files(self):
        import yaml
        for filename, job in [("validate.yml", "validate"), ("publish.yml", "build")]:
            config=yaml.load((ROOT / ".github/workflows" / filename).read_text(), Loader=yaml.BaseLoader)
            steps=config["jobs"][job]["steps"]
            commands=[s.get("run", "") for s in steps]
            generate=commands.index("uv run --no-sync python scripts/build_artifacts.py --target " + ("sites" if job == "validate" else "pages"))
            verify=commands.index("uv run --no-sync python scripts/check_colab.py --execute --language all")
            upload=next(i for i,s in enumerate(steps) if s.get("uses", "").startswith("actions/upload-artifact@"))
            self.assertLess(generate, verify)
            self.assertLess(verify, upload)
            self.assertEqual(steps[upload]["with"]["path"], "_build/colab/")
            self.assertEqual(steps[upload]["with"]["name"], "colab-notebooks")

    def test_book_downloads_match_validated_exports_and_exclude_other_files(self):
        from test_publication import fixture
        from book_colab_downloads import add_downloads
        import shutil
        import zipfile
        with fixture() as root:
            for folder in ["examples", "skills", "plugins", "deploy"]:
                shutil.copytree(ROOT / folder, root / folder, ignore=shutil.ignore_patterns(".generated", "__pycache__"))
            build(root)
            from build_colab_zip import build as package
            package(root)
            (root / "_build/colab/.env.local").write_text("not a distributable file")
            html=root / "_build/html"
            html.mkdir(); (html / "index.html").write_text("book")
            result=add_downloads(html, root)
            self.assertEqual(result["standalone_downloads"], 17)
            with zipfile.ZipFile(html / result["archive"]) as archive:
                self.assertEqual(len(archive.namelist()), 18)
                self.assertNotIn(".env.local", archive.namelist())
                self.assertEqual(archive.read("quickstart.ipynb"), (root / "_build/colab/quickstart.ipynb").read_bytes())
            self.assertFalse((html / "downloads/colab/.env.local").exists())
            (html / "downloads/colab/PROGRESS.md").write_text("unexpected")
            with self.assertRaisesRegex(ValueError, "Unexpected"):
                add_downloads(html, root)


if __name__ == "__main__":
    unittest.main()
