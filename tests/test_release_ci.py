import importlib.util
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
spec = importlib.util.spec_from_file_location("release_ci", SCRIPTS / "release_ci.py")
release_ci = importlib.util.module_from_spec(spec)
sys.path.insert(0, str(SCRIPTS))
try:
    spec.loader.exec_module(release_ci)
finally:
    sys.path.pop(0)
release_module = sys.modules["release"]


class ReleaseInputTests(unittest.TestCase):
    def env(self, **changes):
        return {"GITHUB_EVENT_NAME": "workflow_dispatch", "GITHUB_REF": "refs/heads/main",
                "RELEASE_BUMP": "patch", "RELEASE_VERSION": "", "RELEASE_DRY_RUN": "true", **changes}

    def test_preview_always_runs_full_checks_without_publishing(self):
        self.assertEqual(release_ci.release_command(self.env())[1:], ["patch", "--full-checks", "--dry-run"])

    def test_publish_and_explicit_version(self):
        with patch.object(release_ci, "current_release_version", return_value="0.3.0"):
            self.assertEqual(release_ci.release_command(self.env(RELEASE_VERSION=" 0.4.2 ",
                             RELEASE_DRY_RUN="false"))[1:], ["0.4.2", "--full-checks"])

    def test_other_branches_tags_and_events_are_rejected(self):
        for change in ({"GITHUB_REF": "refs/heads/feature"}, {"GITHUB_REF": "refs/tags/v0.3.0"},
                       {"GITHUB_EVENT_NAME": "pull_request"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                release_ci.release_command(self.env(**change))

    def test_invalid_or_command_like_values_are_rejected(self):
        for value in ("--skip-checks", "0.4.0; echo bad", "$(echo bad)", "v0.4.0", "0.4", "-1.0.0"):
            with self.subTest(value=value), self.assertRaises((ValueError, SystemExit)):
                release_ci.release_command(self.env(RELEASE_VERSION=value))

    def test_downgrades_are_rejected(self):
        with patch.object(release_ci, "current_release_version", return_value="0.3.0"), self.assertRaises(SystemExit):
            release_ci.release_command(self.env(RELEASE_VERSION="0.2.0"))

    def test_latest_release_tag_is_version_source_when_project_metadata_lags(self):
        with patch.object(release_module, "read_version", return_value="0.3.0"), \
             patch.object(release_module, "last_tag", return_value="v0.3.1"):
            self.assertEqual(release_module.current_release_version(), "0.3.1")

    def test_package_version_is_changed_only_in_the_staging_copy(self):
        with tempfile.TemporaryDirectory() as temp:
            staged = Path(temp)
            (staged / "pyproject.toml").write_text('version = "0.3.0"\n')
            (staged / "uv.lock").write_text(
                '[[package]]\nname = "unrelated"\nversion = "1.0.0"\n\n'
                '[[package]]\nname = "lux-in-music"\nversion = "0.3.0"\n'
                'source = { editable = "." }\n'
            )
            release_module.set_project_version(staged, "0.3.2")
            self.assertIn('version = "0.3.2"', (staged / "pyproject.toml").read_text())
            lock = (staged / "uv.lock").read_text()
            self.assertIn('name = "unrelated"\nversion = "1.0.0"', lock)
            self.assertIn('version = "0.3.2"', lock)

    def test_release_source_archive_gets_version_without_mutating_checkout(self):
        original_version = release_module.read_version()
        with tempfile.TemporaryDirectory() as temp:
            source, archive = release_module.stage_release_source("9.8.7", Path(temp))
            staged_version = release_module.re.search(
                r'(?m)^version\s*=\s*"([^"]+)"',
                (source / "pyproject.toml").read_text(),
            ).group(1)
            self.assertEqual(staged_version, "9.8.7")
            zipped = Path(temp) / "release.zip"
            release_module.write_versioned_source_zip(archive, source, zipped, "9.8.7")
            with zipfile.ZipFile(zipped) as result:
                prefix = "lux-in-music-9.8.7/"
                versioned = release_module.re.search(
                    rb'(?m)^version\s*=\s*"([^"]+)"',
                    result.read(prefix + "pyproject.toml"),
                ).group(1)
                self.assertEqual(versioned, b"9.8.7")
                studio = result.getinfo(prefix + "studio.sh")
                self.assertTrue(studio.external_attr >> 16 & 0o100)
        self.assertEqual(release_module.read_version(), original_version)

    def test_invalid_switches_are_rejected(self):
        for change in ({"RELEASE_BUMP": "--no-push"}, {"RELEASE_DRY_RUN": ""}, {"RELEASE_DRY_RUN": "False"}):
            with self.subTest(change=change), self.assertRaises(ValueError):
                release_ci.release_command(self.env(**change))

    def test_invalid_input_never_starts_a_release(self):
        with patch.dict("os.environ", self.env(RELEASE_BUMP="wrong"), clear=True), \
             patch.object(release_ci.subprocess, "run") as run:
            self.assertEqual(release_ci.main(), 2)
            run.assert_not_called()
