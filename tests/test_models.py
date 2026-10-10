"""Offline acceptance tests with small files and a provider independent of audio.cpp."""

import asyncio
import base64
import copy
import hashlib
import io
import json
import tempfile
import threading
import unittest
import wave
from pathlib import Path
from unittest.mock import patch

import httpx

from studio import engine, models, providers
from studio.models import ModelManager, SetupRequired
from studio.params import GenerationParams


def tiny_audio():
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as audio:
        audio.setnchannels(1); audio.setsampwidth(2); audio.setframerate(8000)
        audio.writeframes(b"\0" * 1600)
    return base64.b64encode(buffer.getvalue()).decode()


class FakeAdapter:
    capabilities = {"planning": [], "abc": False, "semantic_edit": False, "options": [], "max_duration_s": 60}

    def normalize(self, params):
        return params

    def request(self, params):
        return {"lyrics": params.lyrics, "style": params.style, "seed": params.seed}


class FakeProvider:
    def __init__(self):
        self.calls = []; self.fail_probe = False; self.token = "test-computer"; self.hold_probe = None

    def adapter(self, profile): return FakeAdapter()
    def compatibility_token(self): return self.token
    def run(self, profile, request):
        self.calls.append((copy.deepcopy(profile), copy.deepcopy(request)))
        return {"audio": tiny_audio(), "sample_rate": 8000, "channels": 1, "artifacts": []}
    def probe(self, profile, cancel=None):
        if self.hold_probe:
            self.hold_probe.wait(3)
        if self.fail_probe:
            raise RuntimeError("This precision cannot run on this device")
        return {"backend": "fake", "compatibility_token": self.token, "smoke_test": "audio"}
    def close(self): pass


class ModelFixtures(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.payloads = {"main-q8.gguf": b"GGUF Q8 test", "main-bf16.gguf": b"GGUF BF16 test",
                         "vae-f16.gguf": b"GGUF F16 test", "vae-f32.gguf": b"GGUF F32 test", "config.json": b"{}"}
        self.provider = FakeProvider()
        provider_patch = patch.dict(providers._providers, {"fake": self.provider})
        provider_patch.start(); self.addCleanup(provider_patch.stop)
        def artifact(name):
            payload = self.payloads[name]
            return {"path": name, "size": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "url": f"https://files.test/{name}"}
        self.catalog = [{"id": "test-model", "name": "Test model", "provider": "fake", "family": "fake", "task": "gen",
                         "revision": "test-release", "install_dir": "test-model", "description": "Test only",
                         "precisions": {"q8_0": artifact("main-q8.gguf"), "bf16": artifact("main-bf16.gguf")},
                         "vaes": {"f16": artifact("vae-f16.gguf"), "f32": artifact("vae-f32.gguf")},
                         "default_precision": "q8_0", "default_vae": "f16", "required": [artifact("config.json")],
                         "licenses": [{"component": "Test weights", "id": "MIT", "url": "https://licenses.test/terms", "summary": "Test only", "verified": True}]}]
        self.requests = []
        self.handler = self.respond
        self.manager = ModelManager(self.root / "state", self.root / "models", self.catalog,
                                    lambda: httpx.Client(transport=httpx.MockTransport(lambda req: self.handler(req))))
        manager_patch = patch.object(models, "_manager", self.manager)
        manager_patch.start(); self.addCleanup(manager_patch.stop)
        output = self.root / "outputs"; output.mkdir()
        output_patch = patch.object(engine, "OUTPUT_DIR", output)
        output_patch.start(); self.addCleanup(output_patch.stop)
        self.addCleanup(self.manager.close)

    def respond(self, request):
        self.assertTrue(json.loads((self.manager.state_dir / "settings.json").read_text())["license_reviews"], "License review must be recorded before transfer")
        self.requests.append(request)
        return httpx.Response(200, content=self.payloads[request.url.path.lstrip("/")])

    def profile(self, precision="q8_0", vae="f16"):
        return self.manager.profile("test-model", precision, vae)

    def setup_profile(self, precision="q8_0", vae="f16", download=True):
        profile = self.profile(precision, vae)
        result = self.manager.start("test-model", precision, vae, profile["license_review_id"], True, download)
        self.manager.threads[-1].join(4)
        self.assertFalse(self.manager.threads[-1].is_alive(), "Setup worker did not finish")
        return self.manager.jobs[result["id"]]


class DownloadTests(ModelFixtures):
    def test_no_files_or_network_on_fresh_install_or_catalog_read(self):
        self.assertTrue(self.manager.status()["setup_required"])
        self.assertEqual(len(self.manager.options()[0]["choices"]), 4)
        self.assertFalse((self.root / "models").exists())
        self.assertFalse(self.requests)
        with self.assertRaises(SetupRequired): self.manager.snapshot()

    def test_licenses_and_release_review_are_required_before_any_transfer(self):
        profile = self.profile()
        for review, accepted in [(profile["license_review_id"], False), ("old-release", True)]:
            with self.assertRaisesRegex(ValueError, "licenses"):
                self.manager.start("test-model", "q8_0", "f16", review, accepted)
        self.catalog[0]["licenses"][0]["verified"] = False
        profile = self.profile()
        with self.assertRaises(ValueError):
            self.manager.start("test-model", "q8_0", "f16", profile["license_review_id"], True)
        self.assertFalse(self.requests)

    def test_downloads_only_the_selected_files_and_persists_profile(self):
        job = self.setup_profile("bf16", "f32")
        self.assertEqual(job["status"], "done", job)
        self.assertEqual({r.url.path.lstrip("/") for r in self.requests}, {"main-bf16.gguf", "vae-f32.gguf", "config.json"})
        saved = ModelManager(self.root / "state", self.root / "models", self.catalog)
        self.assertEqual(saved.snapshot()["precision"], "bf16")
        self.assertEqual(saved.snapshot()["vae_precision"], "f32")
        self.assertIn("license_accepted_at", saved.snapshot())

    def test_reuses_legacy_downloads_without_contacting_the_network(self):
        profile = self.profile()
        old = Path(profile["legacy_root"]); old.mkdir(parents=True)
        for file in profile["files"]: (old / file["path"]).write_bytes(self.payloads[file["path"]])
        self.assertTrue(self.manager.options()[0]["choices"][0]["installed"])
        job = self.setup_profile(download=False)
        self.assertEqual(job["status"], "done", job)
        self.assertFalse(self.requests)
        self.assertTrue(self.manager.snapshot()["root"].endswith("releases/test-release"))

    def test_resume_requires_a_valid_range_and_checks_the_completed_file(self):
        profile = self.profile(); file = profile["files"][0]
        part = Path(profile["root"]) / (file["path"] + ".part"); part.parent.mkdir(parents=True)
        part.write_bytes(self.payloads[file["path"]][:4])
        def ranged(request):
            self.requests.append(request)
            if request.url.path.endswith("main-q8.gguf"):
                self.assertEqual(request.headers["Range"], "bytes=4-")
                return httpx.Response(206, headers={"Content-Range": f"bytes 4-{file['size'] - 1}/{file['size']}"}, content=self.payloads[file["path"]][4:])
            return httpx.Response(200, content=self.payloads[request.url.path.lstrip("/")])
        self.handler = ranged
        self.assertEqual(self.setup_profile()["status"], "done")
        self.assertFalse(part.exists())

    def test_server_ignoring_range_restarts_instead_of_appending(self):
        profile = self.profile(); part = Path(profile["root"]) / "main-q8.gguf.part"
        part.parent.mkdir(parents=True); part.write_bytes(b"old")
        self.assertEqual(self.setup_profile()["status"], "done")
        self.assertEqual((part.parent / "main-q8.gguf").read_bytes(), self.payloads["main-q8.gguf"])

    def test_corrupt_download_is_not_activated_and_can_be_retried(self):
        self.handler = lambda req: httpx.Response(200, content=b"X" * len(self.payloads[req.url.path.lstrip("/")]))
        job = self.setup_profile()
        self.assertEqual(job["status"], "error")
        self.assertIn("Checksum mismatch", job["error"])
        self.assertTrue(self.manager.status()["setup_required"])
        self.handler = self.respond
        self.assertEqual(self.setup_profile()["status"], "done")

    def test_failed_activation_preserves_previous_selection(self):
        self.assertEqual(self.setup_profile()["status"], "done")
        previous = self.manager.snapshot()
        self.provider.fail_probe = True
        job = self.setup_profile("bf16", "f32")
        self.assertEqual(job["status"], "error")
        self.assertEqual(self.manager.snapshot()["id"], previous["id"])
        self.assertFalse(next(c for c in self.manager.options()[0]["choices"] if c["precision"] == "bf16" and c["vae_precision"] == "f32")["ready"])

    def test_failed_settings_write_preserves_selection_in_memory_and_on_disk(self):
        self.assertEqual(self.setup_profile()["status"], "done")
        previous = self.manager.snapshot()
        save = self.manager._save
        def fail_activation_save():
            if self.manager.state["active"] != previous["id"]:
                raise OSError("Disk full while saving the active profile")
            save()
        with patch.object(self.manager, "_save", side_effect=fail_activation_save):
            job = self.setup_profile("bf16", "f32")
        self.assertEqual(job["status"], "error")
        self.assertEqual(self.manager.snapshot()["id"], previous["id"])
        restored = ModelManager(self.root / "state", self.root / "models", self.catalog)
        self.assertEqual(restored.snapshot()["id"], previous["id"])

    def test_cancellation_during_runtime_test_does_not_change_selection(self):
        self.provider.hold_probe = threading.Event()
        p = self.profile(); job = self.manager.start("test-model", "q8_0", "f16", p["license_review_id"], True)
        self.manager.cancel(job["id"]); self.provider.hold_probe.set(); self.manager.threads[-1].join(4)
        self.assertEqual(self.manager.jobs[job["id"]]["status"], "cancelled")
        self.assertTrue(self.manager.status()["setup_required"])

    def test_changed_files_and_changed_backend_require_verification(self):
        self.setup_profile(); profile = self.manager.snapshot()
        self.provider.token = "another-device"
        with self.assertRaises(SetupRequired): self.manager.snapshot()
        self.provider.token = "test-computer"
        main = Path(profile["root"]) / profile["main_file"]
        main.write_bytes(b"X" * main.stat().st_size)
        with self.assertRaises(SetupRequired): self.manager.snapshot()

    def test_fp16_is_not_accepted_as_a_bf16_alias(self):
        with self.assertRaisesRegex(ValueError, "different formats"):
            self.manager.profile("test-model", "fp16", "f32")

    def test_optional_separator_has_no_vae_and_does_not_select_a_generation_model(self):
        separator = copy.deepcopy(self.catalog[0])
        separator.update(id="test-separator", task="sep", mode_id="4stems", vaes={}, default_vae=None)
        self.manager.catalog[separator["id"]] = separator
        profile = self.manager.profile("test-separator", "q8_0")
        job = self.manager.start("test-separator", "q8_0", None, profile["license_review_id"], True)
        self.manager.threads[-1].join(4)
        self.assertEqual(self.manager.jobs[job["id"]]["status"], "done")
        self.assertTrue(self.manager.status()["setup_required"])
        self.assertIsNone(self.manager.separator("4stems")["vae_precision"])
        self.assertFalse(any("vae" in str(req.url) for req in self.requests))

    def test_invalid_download_range_cannot_be_activated(self):
        profile = self.profile(); part = Path(profile["root"]) / "main-q8.gguf.part"
        part.parent.mkdir(parents=True); part.write_bytes(b"GGUF")
        self.handler = lambda req: httpx.Response(206, headers={"Content-Range": "bytes 0-1/2"}, content=b"xx")
        job = self.setup_profile()
        self.assertEqual(job["status"], "error")
        self.assertIn("invalid download range", job["error"])
        self.assertTrue(self.manager.status()["setup_required"])

    def test_insufficient_disk_space_stops_before_a_download(self):
        with patch("studio.models.shutil.disk_usage", return_value=type("Disk", (), {"free": 0})()):
            job = self.setup_profile()
        self.assertEqual(job["status"], "error")
        self.assertIn("disk space", job["error"])
        self.assertFalse(self.requests)


class ProviderBoundaryTests(ModelFixtures):
    def test_cli_does_not_add_default_yue2_options_to_other_providers(self):
        self.setup_profile()
        from studio.cli import main
        from contextlib import redirect_stdout
        with patch("sys.argv", ["studio-gen", "--lyrics", "A song", "--style", "Piano", "--name", "cli-song"]), redirect_stdout(io.StringIO()):
            main()
        meta = json.loads((engine.OUTPUT_DIR / "cli-song.json").read_text())
        self.assertEqual(meta["params"]["model_options"], {})
        self.assertNotIn("cot", meta["params"])

    def test_external_provider_needs_no_local_weights_precision_or_vae(self):
        external = copy.deepcopy(self.catalog[0])
        external.update(id="test-external", delivery="external", precisions={}, vaes={}, required=[], default_precision=None, default_vae=None)
        self.manager.catalog[external["id"]] = external
        profile = self.manager.profile("test-external")
        job = self.manager.start("test-external", None, None, profile["license_review_id"], True, False)
        self.manager.threads[-1].join(4)
        self.assertEqual(self.manager.jobs[job["id"]]["status"], "done")
        self.assertIsNone(self.manager.snapshot()["precision"])
        self.assertFalse((self.root / "models").exists())
        self.assertFalse(self.requests)
        engine.generate(GenerationParams(lyrics="A song", style="Piano"), "external-song")
        self.assertEqual(self.provider.calls[-1][0]["model_id"], "test-external")

    def test_editing_resolves_the_original_profile_and_reports_missing_files(self):
        self.setup_profile(); original = self.manager.snapshot()
        self.setup_profile("bf16", "f32")
        self.assertEqual(self.manager.song_profile({"model_profile": original})["precision"], "q8_0")
        (Path(original["root"]) / original["main_file"]).unlink()
        with self.assertRaises(SetupRequired): self.manager.song_profile({"model_profile": original})

    def test_another_provider_generates_audio_without_yue2_fields(self):
        self.setup_profile()
        result = engine.generate(GenerationParams(lyrics="A song", style="Piano"), "fake-song")
        meta = json.loads(result.meta_path.read_text())
        self.assertEqual(meta["model_profile"]["provider"], "fake")
        self.assertEqual(meta["sample_rate"], 8000)
        self.assertEqual(meta["channels"], 1)
        self.assertAlmostEqual(meta["duration_s"], 0.1)
        self.assertNotIn("semantic_max_tokens", self.provider.calls[0][1])
        self.assertNotIn("cot", self.provider.calls[0][1])

    def test_queued_job_keeps_its_original_profile_after_settings_change(self):
        self.setup_profile()
        from studio import app as api
        with patch.object(api, "_queue"):
            job = api.api_generate(GenerationParams(lyrics="A song", style="Piano"))
        self.setup_profile("bf16", "f32")
        engine.generate(GenerationParams(**job["params"]), "queued-song", job["profile"])
        self.assertEqual(self.provider.calls[-1][0]["precision"], "q8_0")
        self.assertEqual(self.manager.snapshot()["precision"], "bf16")
        api.jobs.pop(job["id"], None)


class SettingsApiTests(ModelFixtures):
    def request(self, method, path, body=None):
        from studio.app import app
        async def send():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://studio.test") as client:
                return await client.request(method, path, json=body)
        return asyncio.run(send())

    def test_settings_and_library_open_with_no_model_or_engine(self):
        self.assertEqual(self.request("GET", "/").status_code, 200)
        self.assertTrue(self.request("GET", "/api/settings/status").json()["setup_required"])
        self.assertEqual(self.request("GET", "/api/library").json(), [])
        self.assertEqual(self.request("POST", "/api/generate", {"lyrics": "A song", "style": "Piano"}).status_code, 409)

    def test_license_gate_is_enforced_by_the_api(self):
        profile = self.profile()
        body = {"model_id": "test-model", "precision": "q8_0", "vae_precision": "f16", "license_review_id": profile["license_review_id"]}
        self.assertEqual(self.request("POST", "/api/settings/download", body).status_code, 422)
        self.assertFalse(self.requests)

    def test_existing_library_metadata_is_readable_without_model_setup(self):
        (engine.OUTPUT_DIR / "old-song.json").write_text(json.dumps({"name": "old-song", "title": "Old song", "created": "2026-10-01", "params": {"lyrics": "A song", "style": "Piano"}, "peaks": []}))
        songs = self.request("GET", "/api/library").json()
        self.assertEqual(songs[0]["title"], "Old song")
        self.assertFalse(songs[0]["can_edit"])
