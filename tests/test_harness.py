import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts.check import check_branding, project_files, read_requirements, run_tests


class HarnessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def test_brand_guard_catches_case_changes_in_code_and_filenames(self):
        text = self.root / "module.py"
        text.write_text('# ' + 'Su' + 'NO' + ' prototype\n')
        with self.assertRaisesRegex(ValueError, "module.py:1"):
            check_branding(self.root, project_files(self.root))
        text.unlink()
        named = self.root / ("su" + "no" + "_helper.py")
        named.write_text("pass\n")
        with self.assertRaisesRegex(ValueError, "helper.py"):
            check_branding(self.root, project_files(self.root))

    def test_source_archive_excludes_model_and_output_data(self):
        for folder in ("models", "outputs", "vendor", ".venv"):
            path = self.root / folder
            path.mkdir()
            (path / "generated.txt").write_text("Su" + "no")
        (self.root / "README.md").write_text("Lux In Music")
        files = project_files(self.root)
        self.assertEqual([p.name for p in files], ["README.md"])
        check_branding(self.root, files)

    def ledger(self, status, tests):
        folder = self.root / "harness"
        folder.mkdir(exist_ok=True)
        (folder / "requirements.json").write_text(json.dumps({
            "schema_version": 1,
            "requirements": [{"id": "setup", "issue": "https://github.com/lvxworld/lux-in-music/issues/3",
                              "description": "Open Settings", "status": status,
                              "tests": tests, "acceptance": ["Open a fresh install"]}],
        }))

    def test_planned_behavior_cannot_be_marked_implemented_without_tests(self):
        self.ledger("planned", [])
        self.assertEqual(read_requirements(self.root)[0]["status"], "planned")
        self.ledger("implemented", [])
        with self.assertRaisesRegex(ValueError, "no verification"):
            read_requirements(self.root)

    def test_missing_test_selector_fails_instead_of_passing_empty_suite(self):
        with self.assertRaisesRegex(ValueError, "Missing or empty"):
            run_tests(["tests.test_harness.DoesNotExist"])

    def test_skipped_verification_cannot_establish_completion(self):
        with contextlib.redirect_stderr(io.StringIO()):
            with self.assertRaisesRegex(ValueError, "skipped"):
                run_tests(["tests.test_harness._SkippedVerification"])


class _SkippedVerification(unittest.TestCase):
    # Loaded explicitly to test the verifier; excluded from normal discovery below.
    @unittest.skip("test fixture")
    def test_fixture(self):
        pass


def load_tests(loader, tests, pattern):
    return loader.loadTestsFromTestCase(HarnessTests)
