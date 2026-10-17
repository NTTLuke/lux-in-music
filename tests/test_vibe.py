import asyncio
import base64
import hashlib
import json
import os
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx
import numpy as np
from tests.test_models import ModelFixtures
from studio.artwork import prepare_vibe_artwork

from studio.vibe import (LICENSE_ID, LICENSE_REVIEW_ID, MODEL, MODEL_ID, REVISION, LocalEmbeddingRuntime, VibeManager,
                         bounded_download_progress, source_mismatches, load_catalog, normalize, rank_catalog,
                         blend_catalog, report_snapshot_progress, validate_image, vibe_runtime_status)


class VibeCatalogTests(unittest.TestCase):
    def test_artwork_requires_a_valid_image_and_catalog_reference(self):
        self.assertIsNone(prepare_vibe_artwork(None, None))
        entry_id = load_catalog()[0]["id"]
        for image, entry in (("%%%", entry_id), ("", entry_id), (None, entry_id), ("eA==", "missing")):
            with self.subTest(image=image, entry=entry), self.assertRaises(ValueError):
                prepare_vibe_artwork(image, entry)
        with patch("studio.artwork.validate_image", side_effect=ValueError("Invalid synthetic image")) as validate:
            with self.assertRaisesRegex(ValueError, "Invalid synthetic image"):
                prepare_vibe_artwork(base64.b64encode(b"invalid synthetic image").decode(), entry_id)
        validate.assert_called_once_with(b"invalid synthetic image")
        for items in ([], [{"image": "eA==", "entry_id": entry_id}] * 6):
            with self.assertRaises(ValueError):
                prepare_vibe_artwork(None, None, items)
    def test_catalog_has_unique_valid_entries(self):
        catalog = load_catalog()
        self.assertGreaterEqual(len(catalog), 120)
        self.assertEqual(len({row["id"] for row in catalog}), len(catalog))
        self.assertTrue(all(row["visual"].strip() and row["style"].strip() for row in catalog))

    def test_image_blend_uses_a_shared_direction_and_each_images_textures(self):
        catalog = [{"id": "a", "style": "Synthetic jazz, brass, piano"},
                   {"id": "b", "style": "Synthetic folk, fiddle, guitar"},
                   {"id": "c", "style": "Synthetic fusion, keys, percussion"}]
        vectors = np.array([[1, 0], [0, 1], [1, 1]])
        result = blend_catalog([[3, 0], [0, 4]], vectors, catalog)
        self.assertEqual(result["id"], "c")
        self.assertEqual(result["entry_ids"], ["a", "b"])
        self.assertIn("brass", result["style"])
        self.assertIn("fiddle", result["style"])
        self.assertEqual(result, blend_catalog([[3, 0], [0, 4]], vectors, catalog))
        self.assertGreater(result["diversity"], 0)
        same = blend_catalog([[1, 0], [1, 0]], vectors, catalog)
        self.assertEqual(same["diversity"], 0)
        self.assertEqual(same["style"], catalog[0]["style"])
        for images in ([], [[1, 0]] * 6):
            with self.assertRaises(ValueError):
                blend_catalog(images, vectors, catalog)

    def test_image_sampling_presets_are_valid_yue2_inputs_and_vary_conservatively(self):
        from studio.adapters.yue2 import YuE2Adapter
        from studio.params import GenerationParams
        adapter = YuE2Adapter()
        presets = [adapter.vibe_options(value) for value in (0, .12, .3)]
        for preset in presets:
            normalized = adapter.normalize(GenerationParams(style="Synthetic instrumental direction", model_options=preset["options"]))
            request = adapter.request(normalized)
            self.assertNotIn("vibe", request)
            self.assertGreaterEqual(normalized.semantic_temperature, .9)
            self.assertLessEqual(normalized.semantic_temperature, 1.1)
            self.assertEqual(normalized.num_inference_steps, 8)
            self.assertEqual(request["options"]["num_inference_steps"], "8")
        self.assertGreater(presets[-1]["options"]["semantic_top_k"], presets[0]["options"]["semantic_top_k"])
        with self.assertRaises(ValueError):
            adapter.vibe_options(float("nan"))

    def test_normalization_rejects_invalid_vectors(self):
        np.testing.assert_allclose(normalize(np.array([3, 4])), [0.6, 0.8])
        for vector in (np.array([0, 0]), np.array([np.nan, 1])):
            with self.subTest(vector=vector), self.assertRaises(ValueError):
                normalize(vector)

    def test_similarity_selection_is_deterministic_on_ties(self):
        catalog = [{"id": "z", "style": "second"}, {"id": "a", "style": "first"}]
        result = rank_catalog(np.array([1.0, 0.0]), np.array([[1.0, 0.0], [1.0, 0.0]]), catalog)
        self.assertEqual(result["id"], "a")

    def test_dimension_mismatch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "dimensions"):
            rank_catalog(np.array([1, 0]), np.array([[1, 0, 0]]), [{"id": "a"}])

    def test_invalid_and_oversized_images_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "20 MB"):
            validate_image(b"x" * (20 * 1024 * 1024 + 1))
        with self.assertRaises(ValueError):
            validate_image(b"not an image")

    def with_fake_pillow(self, image_format="PNG", width=4, height=3):
        calls = []
        class FakeImage:
            format = image_format
            mode = "RGBA"
            def __init__(self): self.width, self.height = width, height
            def __enter__(self): return self
            def __exit__(self, *_): return False
            def verify(self): calls.append("verify")
            def load(self): calls.append("load")
            def draft(self, mode, size): calls.append("draft")
            def thumbnail(self, size):
                calls.append("thumbnail")
                scale = min(1, size[0] / self.width, size[1] / self.height)
                self.width, self.height = round(self.width * scale), round(self.height * scale)
            def convert(self, mode): self.mode = mode; return self
            def copy(self): return self
        image_module = types.ModuleType("PIL.Image")
        image_module.open = lambda *_: FakeImage()
        image_ops = types.ModuleType("PIL.ImageOps")
        image_ops.exif_transpose = lambda image: (calls.append("exif"), image)[1]
        pil = types.ModuleType("PIL")
        pil.Image, pil.ImageOps = image_module, image_ops
        return patch.dict("sys.modules", {"PIL": pil, "PIL.Image": image_module, "PIL.ImageOps": image_ops}), calls

    def test_valid_png_is_verified_oriented_and_converted_to_rgb(self):
        fake, calls = self.with_fake_pillow()
        with fake:
            image = validate_image(b"synthetic PNG bytes")
        self.assertEqual(image.mode, "RGB")
        self.assertEqual((image.width, image.height), (4, 3))
        self.assertEqual(calls, ["verify", "draft", "exif", "load", "thumbnail"])

    def test_multi_picture_jpeg_from_a_camera_is_accepted(self):
        fake, calls = self.with_fake_pillow(image_format="MPO")
        with fake:
            image = validate_image(b"synthetic MPO bytes")
        self.assertEqual(image.mode, "RGB")
        self.assertEqual(calls, ["verify", "draft", "exif", "load", "thumbnail"])

    def test_actual_file_format_and_pixel_limit_are_enforced(self):
        fake, _ = self.with_fake_pillow(image_format="GIF")
        with fake, self.assertRaisesRegex(ValueError, "JPG, PNG, or WebP"):
            validate_image(b"image bytes")
        fake, _ = self.with_fake_pillow(width=10000, height=9000)
        with fake, self.assertRaisesRegex(ValueError, "89 megapixels"):
            validate_image(b"image bytes")

    def test_phone_camera_resolution_is_accepted_and_downscaled_for_analysis(self):
        fake, _ = self.with_fake_pillow(image_format="JPEG", width=8064, height=6048)
        with fake:
            image = validate_image(b"synthetic 48 MP bytes")
        self.assertEqual((image.width, image.height), (2048, 1536))


class VibeManagerTests(unittest.TestCase):
    def test_download_progress_is_byte_based_and_bounded(self):
        self.assertEqual(bounded_download_progress(102, 100), (100, 100))
        self.assertEqual(bounded_download_progress(-5, 100), (0, 100))
        self.assertEqual(bounded_download_progress(20, 0), (0, 0))
        events = []
        progress = lambda done, total, desc: events.append((done, total, desc))
        report_snapshot_progress(progress, "Downloading bytes", 1_090, 1_530)
        report_snapshot_progress(progress, "Fetching 13 files", 12, 13)
        report_snapshot_progress(progress, "Reconstructing snapshot", 1_550, 1_530)
        self.assertEqual(events, [(1_530, 1_530, "Reconstructing snapshot")])

    def test_runtime_requires_sentence_transformers_version_declared_by_model(self):
        with patch("studio.vibe.importlib.util.find_spec", return_value=object()), \
             patch("studio.vibe.metadata.version", return_value="5.7.0"):
            self.assertFalse(vibe_runtime_status()["compatible"])
        with patch("studio.vibe.importlib.util.find_spec", return_value=object()), \
             patch("studio.vibe.metadata.version", return_value="6.1.0"):
            self.assertTrue(vibe_runtime_status()["compatible"])

    def test_runtime_requires_image_dependencies_even_with_a_current_version(self):
        with patch("studio.vibe.importlib.util.find_spec", side_effect=lambda name: None if name == "torchvision" else object()), \
             patch("studio.vibe.metadata.version", return_value="6.1.0"):
            status = vibe_runtime_status()
        self.assertFalse(status["compatible"])
        self.assertEqual(status["missing"], ["torchvision"])

    def test_model_is_never_downloaded_by_construction_or_status(self):
        with tempfile.TemporaryDirectory() as temp:
            downloader = unittest.mock.Mock()
            manager = VibeManager(Path(temp) / "weights", downloader)
            self.assertFalse(manager.status()["installed"])
            downloader.assert_not_called()

    def test_license_acceptance_is_restored_only_for_the_current_review(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = VibeManager(Path(temp) / "weights")
            manager.state_path = Path(temp) / "state.json"
            manager.state_path.write_text(json.dumps({
                "license": LICENSE_ID,
                "license_review_id": LICENSE_REVIEW_ID,
            }))
            self.assertTrue(manager.status()["license_accepted"])
            manager.state_path.write_text(json.dumps({
                "license": LICENSE_ID,
                "license_review_id": "older-review",
            }))
            self.assertFalse(manager.status()["license_accepted"])

    def test_license_acknowledgement_is_required_before_install(self):
        with tempfile.TemporaryDirectory() as temp:
            manager = VibeManager(Path(temp) / "weights", lambda *_: self.fail("download started"))
            with self.assertRaisesRegex(ValueError, "Review and accept"):
                manager.start_install(LICENSE_REVIEW_ID, False)

    @staticmethod
    def pinned(contents):
        """Synthetic catalog entries pinned like the real one: SHA-256 for weights, git blob IDs otherwise."""
        files = []
        for name, data in contents.items():
            if name.endswith(".safetensors"):
                files.append({"path": name, "size": len(data), "sha256": hashlib.sha256(data).hexdigest(), "git_sha1": None})
            else:
                blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
                files.append({"path": name, "size": len(data), "sha256": None, "git_sha1": blob})
        return files

    def install(self, manager):
        with patch("studio.vibe.importlib.util.find_spec", return_value=object()), \
             patch("studio.vibe.metadata.version", return_value="6.1.0"):
            job = manager.start_install(LICENSE_REVIEW_ID, True)
            for _ in range(200):
                if manager.job["status"] in {"done", "error"}:
                    break
                threading.Event().wait(0.01)
        return job

    def test_explicit_install_verifies_files_against_pinned_catalog_hashes(self):
        contents = {"config.json": b'{"model_type":"gemma3"}', "model.safetensors": b"synthetic test weights"}
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            def download(destination, progress):
                for name, data in contents.items():
                    (destination / name).write_bytes(data)
                progress(len(contents["model.safetensors"]), len(contents["model.safetensors"]), "model.safetensors")
            manager = VibeManager(root / "weights", download, self.pinned(contents))
            manager.state_path = root / "state.json"
            job = self.install(manager)
            self.assertEqual(manager.job["status"], "done", manager.job)
            self.assertTrue(manager.status()["installed"])
            state = json.loads(manager.state_path.read_text())
            self.assertEqual(state["revision"], REVISION)
            self.assertEqual(state["license_review_id"], LICENSE_REVIEW_ID)
            self.assertEqual(state["manifest"]["model.safetensors"]["hash"], hashlib.sha256(contents["model.safetensors"]).hexdigest())
            self.assertIn(job["id"], manager.job["id"])
            manager.model_path.joinpath("model.safetensors").write_bytes(b"corrupt weights!!!!!!")
            self.assertFalse(manager._verify_hashes())
            self.assertFalse(manager.status()["installed"])

    def test_download_that_differs_from_the_pinned_hash_is_rejected_and_removed(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            pinned = self.pinned({"config.json": b"{}", "model.safetensors": b"expected weights"})
            def download(destination, progress):
                (destination / "config.json").write_bytes(b"{}")
                (destination / "model.safetensors").write_bytes(b"tampered weights")
            manager = VibeManager(root / "weights", download, pinned)
            manager.state_path = root / "state.json"
            self.install(manager)
            self.assertEqual(manager.job["status"], "error")
            self.assertIn("Checksum mismatch: model.safetensors", manager.job["error"])
            self.assertFalse(manager.model_path.joinpath("model.safetensors").exists())
            self.assertFalse(manager.state_path.exists())
            self.assertFalse(manager.status()["installed"])

    def test_source_metadata_must_match_the_pinned_catalog_before_download(self):
        pinned = self.pinned({"config.json": b"{}", "model.safetensors": b"expected weights"})
        weights, config = pinned[1], pinned[0]
        sibling = lambda name, size, blob_id=None, sha256=None: types.SimpleNamespace(
            rfilename=name, size=size, blob_id=blob_id, lfs={"sha256": sha256} if sha256 else None)
        matching = [sibling("config.json", config["size"], config["git_sha1"]),
                    sibling("model.safetensors", weights["size"], "pointer-oid", weights["sha256"]),
                    sibling("README.md", 10, "readme")]
        self.assertEqual(source_mismatches(pinned, matching), [])
        changed = [sibling("config.json", config["size"], "0" * 40),
                   sibling("model.safetensors", weights["size"], "pointer-oid", "f" * 64)]
        self.assertEqual(source_mismatches(pinned, changed), ["config.json", "model.safetensors"])
        self.assertEqual(source_mismatches(pinned, matching[:1]), ["model.safetensors"])

    def test_vibe_model_and_license_review_come_from_the_shared_catalog(self):
        catalog = json.loads((Path(__file__).parent.parent / "config/model-catalog.json").read_text())
        entry = next(m for m in catalog["optional_models"] if m["id"] == "embeddinggemma-2")
        self.assertEqual((MODEL_ID, REVISION), (entry["repo"], entry["revision"]))
        self.assertNotIn(entry["id"], {m["id"] for m in catalog["models"]})
        review = {"model": entry["id"], "revision": entry["revision"], "licenses": entry["licenses"]}
        self.assertEqual(LICENSE_REVIEW_ID, hashlib.sha256(json.dumps(review, sort_keys=True).encode()).hexdigest())
        status = VibeManager(Path(tempfile.gettempdir()) / "lux-vibe-unused").status()
        self.assertEqual(status["licenses"], entry["licenses"])
        self.assertEqual(status["total_bytes"], sum(f["size"] for f in entry["files"]))

    def test_runtime_update_keeps_the_running_interpreter_and_packages(self):
        with tempfile.TemporaryDirectory() as temp:
            def download(destination, progress):
                (destination / "model.safetensors").write_bytes(b"synthetic test weights")
            manager = VibeManager(Path(temp) / "weights", download,
                                  self.pinned({"model.safetensors": b"synthetic test weights"}))
            manager.state_path = Path(temp) / "state.json"
            runtimes = iter([{"compatible": False, "installed_version": None, "missing": ["torch"]},
                             {"compatible": True, "installed_version": "6.1.0", "missing": []}])
            completed = types.SimpleNamespace(returncode=0)
            job = {"id": "synthetic"}
            with patch("studio.vibe.vibe_runtime_status", side_effect=lambda: next(runtimes)), \
                 patch("studio.vibe.shutil.which", return_value="/fake/uv"), \
                 patch("studio.vibe.subprocess.run", return_value=completed) as run:
                manager._install(job)
            command = run.call_args.args[0]
            self.assertEqual(job["status"], "done", job)
            self.assertTrue(job["restart_required"])
            self.assertIn("--inexact", command)
            self.assertEqual(command[command.index("--python") + 1], sys.executable)

    def test_runtime_uses_local_only_text_image_model_without_audio(self):
        calls = {}
        class FakeModel:
            def __init__(self, *args, **kwargs): calls["init"] = (args, kwargs)
            def eval(self): pass
            def encode(self, data, **kwargs):
                if isinstance(data, list):
                    calls["catalog_calls"] = calls.get("catalog_calls", 0) + 1
                    return np.tile(np.eye(1, 768, 0, dtype=np.float32), (len(data), 1))
                calls["image_calls"] = calls.get("image_calls", 0) + 1
                return np.eye(1, 768, 0, dtype=np.float32)[0]
        st = types.ModuleType("sentence_transformers")
        st.SentenceTransformer = FakeModel
        torch = types.ModuleType("torch")
        torch.float32 = "float32"
        torch.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: False))
        with tempfile.TemporaryDirectory() as temp, patch.dict("sys.modules", {"sentence_transformers": st, "torch": torch}), \
             patch.dict("os.environ"), \
             patch("studio.vibe.importlib.util.find_spec", return_value=object()), \
             patch("studio.vibe.metadata.version", return_value="6.1.0"):
            for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE"):
                os.environ.pop(name, None)
            runtime = LocalEmbeddingRuntime(Path(temp) / REVISION)
            selected = runtime.analyze(object())
            combined = runtime.analyze_many([object()] * 5)
            # Process-wide offline flags would block a later verify/repair download.
            self.assertEqual([name for name in ("HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE") if name in os.environ], [])
        self.assertEqual(selected["id"], min(row["id"] for row in load_catalog()))
        init_kwargs = calls["init"][1]
        self.assertTrue(init_kwargs["local_files_only"])
        self.assertEqual(init_kwargs["config_kwargs"], {"audio_config": None})
        self.assertEqual(init_kwargs["model_kwargs"]["torch_dtype"], "float32")
        self.assertEqual(len(combined["entry_ids"]), 5)
        self.assertEqual(calls["catalog_calls"], 1)
        self.assertEqual(calls["image_calls"], 6)

    def test_release_only_clears_metal_cache_for_an_available_metal_device(self):
        for device, available, calls in (("cpu", True, 0), ("mps", False, 0), ("mps", True, 1)):
            with self.subTest(device=device, available=available):
                torch = types.ModuleType("torch")
                torch.backends = types.SimpleNamespace(mps=types.SimpleNamespace(is_available=lambda: available))
                torch.mps = types.SimpleNamespace(empty_cache=unittest.mock.Mock())
                runtime = LocalEmbeddingRuntime(Path("unused-synthetic-model"))
                runtime.model = types.SimpleNamespace(device=device)
                with patch.dict("sys.modules", {"torch": torch}):
                    runtime.close()
                self.assertIsNone(runtime.model)
                self.assertEqual(torch.mps.empty_cache.call_count, calls)

    def test_embedding_settings_do_not_read_or_change_music_profile(self):
        from studio.app import app
        class Manager:
            def status(self):
                return {"model_id": MODEL_ID, "installed": False, "job": None}
        with patch("studio.app.get_vibe_manager", return_value=Manager()), \
             patch("studio.app.get_manager", side_effect=AssertionError("music settings must remain independent")):
            async def call():
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
                    return await client.get("/api/vibe/status")
            response = asyncio.run(call())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()["installed"])


class VibeArtworkJobTests(ModelFixtures):
    def test_advanced_suggestions_follow_adapter_capabilities_without_changing_profile(self):
        from studio import app as api
        from studio.adapters.yue2 import YuE2Adapter
        self.setup_profile()
        original = self.manager.snapshot()
        self.assertIsNone(api.vibe_advanced_options({"diversity": .3}))
        adapter = types.SimpleNamespace(capabilities={"options": ["semantic_temperature"]}, vibe_options=YuE2Adapter.vibe_options)
        with patch.object(self.provider, "adapter", return_value=adapter):
            suggestion = api.vibe_advanced_options({"diversity": .3})
        self.assertEqual(set(suggestion["options"]), {"semantic_temperature"})
        self.assertEqual(self.manager.snapshot(), original)
    def test_gallery_covers_are_owned_by_each_variation_and_all_deleted_with_the_song(self):
        from studio import app as api, engine
        self.setup_profile()
        entry_id = load_catalog()[0]["id"]
        artwork = {"image": b"synthetic composite", "entry_id": entry_id,
                   "images": [{"image": bytes([i]), "entry_id": entry_id} for i in range(5)]}
        with patch.object(api, "_queue") as pending, patch.object(api, "prepare_vibe_artwork", return_value=artwork):
            job = api.api_generate(api.GenerateRequest(style="Synthetic piano", variations=2,
                vibe_images=[{"image": "synthetic", "entry_id": entry_id}] * 5))
            self.addCleanup(api.jobs.pop, job["id"], None)
            self.assertNotIn("vibe_images", job["params"])
            pending.get.side_effect = [job["id"], StopIteration]
            with self.assertRaises(StopIteration):
                api._worker()
        completed = api.jobs[job["id"]]
        self.assertEqual(completed["status"], "done", completed)
        first, second = completed["result"]["songs"]
        self.assertEqual(first["vibe"]["image_count"], 5)
        self.assertEqual(len(first["vibe"]["images"]), 5)
        first_files = {engine.OUTPUT_DIR / image["file"] for image in first["vibe"]["images"]}
        second_files = {engine.OUTPUT_DIR / image["file"] for image in second["vibe"]["images"]}
        self.assertFalse(first_files & second_files)
        api.api_delete_song(first["name"])
        self.assertFalse(any(path.exists() for path in first_files))
        self.assertTrue(all(path.exists() for path in second_files))
        self.assertNotIn("vibe_images", second["params"])
    def test_variations_keep_independent_covers_outside_model_inputs_and_delete_cleanly(self):
        from studio import app as api, engine
        self.setup_profile()
        artwork = {"image": b"sanitized synthetic JPEG", "entry_id": load_catalog()[0]["id"]}
        with patch.object(api, "_queue") as pending, patch.object(api, "prepare_vibe_artwork", return_value=artwork):
            job = api.api_generate(api.GenerateRequest(style="Synthetic piano direction", variations=2,
                vibe_image="synthetic-upload", vibe_entry_id=artwork["entry_id"]))
            self.addCleanup(api.jobs.pop, job["id"], None)
            self.assertNotIn("vibe_image", job["params"])
            self.assertNotIn("vibe_entry_id", job["params"])
            self.assertNotIn("_vibe_artwork", job)
            pending.get.side_effect = [job["id"], StopIteration]
            with self.assertRaises(StopIteration):
                api._worker()
        completed = api.jobs[job["id"]]
        self.assertEqual(completed["status"], "done", completed)
        self.assertNotIn("_vibe_artwork", completed)
        songs = completed["result"]["songs"]
        self.assertEqual(len(songs), 2)
        paths = [engine.OUTPUT_DIR / song["artifacts"]["vibe_image"] for song in songs]
        self.assertNotEqual(paths[0], paths[1])
        for song, path in zip(songs, paths):
            self.assertEqual(song["vibe"]["entry_id"], artwork["entry_id"])
            self.assertEqual(path.read_bytes(), artwork["image"])
            self.assertNotIn("vibe_image", song["params"])
        self.assertTrue(all("vibe_image" not in request for _, request in self.provider.calls))
        api.api_delete_song(songs[0]["name"])
        self.assertFalse(paths[0].exists())
        self.assertTrue(paths[1].exists())

    def test_queued_cancellation_releases_pending_image_and_returns_public_job(self):
        from studio import app as api
        self.setup_profile()
        with patch.object(api, "_queue"), patch.object(api, "prepare_vibe_artwork", return_value={"image": b"synthetic"}):
            job = api.api_generate(api.GenerateRequest(style="Synthetic piano direction"))
        self.addCleanup(api.jobs.pop, job["id"], None)
        cancelled = api.api_cancel_job(job["id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertNotIn("_vibe_artwork", cancelled)
        self.assertNotIn("_vibe_artwork", api.jobs[job["id"]])


class VibeApiTests(unittest.TestCase):
    def setUp(self):
        options = patch("studio.app.vibe_advanced_options", return_value=None)
        options.start(); self.addCleanup(options.stop)
    @classmethod
    def setUpClass(cls):
        from studio.app import app
        cls.app = app

    def get(self, path):
        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                return await client.get(path)
        return asyncio.run(call())

    def post(self, path, **kwargs):
        async def call():
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=self.app), base_url="http://test") as client:
                return await client.post(path, **kwargs)
        return asyncio.run(call())

    def test_runtime_update_restarts_only_when_no_work_is_active(self):
        from studio import app as studio_app
        manager = types.SimpleNamespace(job={"restart_required": True})
        busy = iter([True, True, False])
        restarted = []
        with patch("studio.app.get_vibe_manager", return_value=manager), \
             patch("studio.app._busy", side_effect=lambda: next(busy)), \
             patch("studio.app._restart_server", lambda: restarted.append(True)):
            studio_app._restart_after_runtime_update(interval=0)
        self.assertEqual(restarted, [True])

    def test_active_generation_or_download_blocks_automatic_restart(self):
        from studio import app as studio_app
        idle = types.SimpleNamespace(status=lambda: {"jobs": [{"status": "done"}]})
        downloading = types.SimpleNamespace(status=lambda: {"jobs": [{"status": "running"}]})
        with patch.dict("studio.app.jobs", {}, clear=True), patch("studio.app.get_manager", return_value=idle):
            self.assertFalse(studio_app._busy())
            studio_app.jobs["synthetic"] = {"status": "queued"}
            self.assertTrue(studio_app._busy())
        with patch.dict("studio.app.jobs", {}, clear=True), patch("studio.app.get_manager", return_value=downloading):
            self.assertTrue(studio_app._busy())

    def test_navigation_order_and_dedicated_vibe_screen(self):
        page = self.get("/").text
        ids = [page.index(f'id="{name}"') for name in ("nav-create", "nav-vibe", "nav-lux", "nav-settings")]
        self.assertEqual(ids, sorted(ids))
        self.assertIn('href="#/vibe"', page)
        self.assertIn('id="vibe"', page)
        self.assertIn("vibe.js", page)

    def test_missing_model_is_clear_and_does_not_attempt_inference(self):
        class Manager:
            def status(self): return {"installed": False}
            def analyze(self, image): self.fail("inference must not run")
        with patch("studio.app.get_vibe_manager", return_value=Manager()):
            response = self.post("/api/vibe/analyze", content=b"arbitrary", headers={"content-type": "image/png"})
        self.assertEqual(response.status_code, 409)
        self.assertIn("Settings", response.json()["detail"])

    def test_success_returns_style_without_embeddings_or_scores(self):
        expected = {"id": "synthetic-style", "style": "Synthetic jazz direction"}
        class Manager:
            def status(self): return {"installed": True, "job": None}
            def analyze(self, image): return expected
        with patch("studio.app.get_vibe_manager", return_value=Manager()), \
             patch("studio.app.validate_image", return_value=object()):
            response = self.post("/api/vibe/analyze", content=b"synthetic", headers={"content-type": "image/png"})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["entry_id"], expected["id"])
        self.assertEqual(response.json()["style"], expected["style"])
        self.assertNotIn("embedding", response.json())
        self.assertNotIn("score", response.json())

    def test_incompatible_runtime_explains_settings_repair_and_keeps_model(self):
        class Manager:
            def status(self): return {"installed": True, "runtime_compatible": False, "runtime_version": "5.7.0"}
            def analyze(self, image): self.fail("inference must wait for a runtime update")
        with patch("studio.app.get_vibe_manager", return_value=Manager()):
            response = self.post("/api/vibe/analyze", content=b"synthetic", headers={"content-type": "image/png"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("5.7.0", response.json()["detail"])
        self.assertIn("Update Vibe runtime", response.json()["detail"])
        self.assertIn("reused", response.json()["detail"])

    def test_runtime_update_requires_stopping_the_server_process(self):
        class Manager:
            def status(self):
                return {"installed": True, "runtime_compatible": True,
                        "runtime_version": "6.1.0", "job": {"restart_required": True}}
            def analyze(self, image): self.fail("old process must not try to analyze")
        with patch("studio.app.get_vibe_manager", return_value=Manager()):
            response = self.post("/api/vibe/analyze", content=b"synthetic", headers={"content-type": "image/png"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("Ctrl+C", response.json()["detail"])
        self.assertIn("Refreshing the browser does not restart", response.json()["detail"])

    def test_missing_image_dependencies_explain_runtime_update_without_redownload(self):
        class Manager:
            def status(self):
                return {"installed": True, "runtime_compatible": False,
                        "runtime_version": "6.1.0", "runtime_missing": ["torchvision"], "job": None}
        with patch("studio.app.get_vibe_manager", return_value=Manager()):
            response = self.post("/api/vibe/analyze", content=b"synthetic", headers={"content-type": "image/png"})
        self.assertEqual(response.status_code, 503)
        self.assertIn("image runtime is incomplete", response.json()["detail"])
        self.assertIn("model files will be reused", response.json()["detail"])

    def test_multipart_upload_is_supported(self):
        expected = {"id": "synthetic-style", "style": "Synthetic jazz direction"}
        class Manager:
            def status(self): return {"installed": True}
            def analyze(self, image): return expected
        with patch("studio.app.get_vibe_manager", return_value=Manager()), \
             patch("studio.app.validate_image", return_value=object()) as validator:
            response = self.post("/api/vibe/analyze", files={"image": ("private-name.jpg", b"synthetic", "image/jpeg")})
        self.assertEqual(response.status_code, 200)
        validator.assert_called_once_with(b"synthetic")

    def test_five_images_are_decoded_and_matched_in_order_without_exposing_vectors(self):
        seen = []
        class Manager:
            def status(self): return {"installed": True}
            def analyze_many(self, images):
                seen.extend(images)
                return {"id": "a", "style": "Synthetic layered piano", "entry_ids": ["a"] * 5, "diversity": .2}
        with patch("studio.app.get_vibe_manager", return_value=Manager()), \
             patch("studio.app.validate_image", side_effect=lambda data: data):
            response = self.post("/api/vibe/analyze", files=[("images", (f"synthetic-{i}.png", bytes([i]), "image/png")) for i in range(5)])
        self.assertEqual(response.status_code, 200)
        self.assertEqual(seen, [bytes([i]) for i in range(5)])
        self.assertEqual(response.json()["image_count"], 5)
        self.assertEqual(response.json()["entry_ids"], ["a"] * 5)
        self.assertNotIn("diversity", response.json())

    def test_six_images_and_malformed_members_are_rejected_before_a_result(self):
        class Manager:
            def status(self): return {"installed": True}
            def analyze_many(self, images):
                return list(images)
        with patch("studio.app.get_vibe_manager", return_value=Manager()), \
             patch("studio.app.validate_image", side_effect=ValueError("Invalid synthetic image")):
            response = self.post("/api/vibe/analyze", files=[("images", ("synthetic.png", b"x", "image/png"))] * 6)
            self.assertEqual(response.status_code, 422)
            response = self.post("/api/vibe/analyze", files=[("images", ("synthetic.png", b"x", "image/png"))] * 2)
            self.assertEqual(response.status_code, 422)
            self.assertIn("Invalid synthetic image", response.json()["detail"])

    def test_each_image_has_its_own_upload_size_limit(self):
        class Manager:
            def status(self): return {"installed": True}
        with patch("studio.app.get_vibe_manager", return_value=Manager()), patch("studio.app.MAX_IMAGE_BYTES", 3):
            response = self.post("/api/vibe/analyze", files=[("images", ("a.png", b"abc", "image/png")), ("images", ("b.png", b"abcd", "image/png"))])
        self.assertEqual(response.status_code, 413)

    def test_inference_failure_is_a_clear_service_response(self):
        class Manager:
            def status(self): return {"installed": True}
            def analyze(self, image): raise RuntimeError("private local error")
        with patch("studio.app.get_vibe_manager", return_value=Manager()), \
             patch("studio.app.validate_image", return_value=object()):
            response = self.post("/api/vibe/analyze", content=b"synthetic", headers={"content-type": "image/png"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("private local error", response.text)


if __name__ == "__main__":
    unittest.main()
