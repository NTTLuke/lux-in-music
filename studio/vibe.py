"""Optional local EmbeddingGemma installation and image-to-style matching."""

from __future__ import annotations

import hashlib
import io
import importlib.util
from importlib import metadata
import json
import math
import os
import shutil
import subprocess
import threading
import uuid
from pathlib import Path
from typing import Callable

import numpy as np

MODEL_ID = "google/embeddinggemma-2"
REVISION = "c3f2237ce16fe33d1bb9dab8692c29c79865bdeb"
LICENSE_ID = "Apache-2.0"
LICENSE_URL = "https://www.apache.org/licenses/LICENSE-2.0"
GEMMA_TERMS_URL = "https://ai.google.dev/gemma/terms"
LICENSE_REVIEW_ID = f"{MODEL_ID}@{REVISION}:{LICENSE_ID}+Google-Gemma-Terms"
MODEL_URL = f"https://huggingface.co/{MODEL_ID}/tree/{REVISION}"
MAX_IMAGE_BYTES = 10 * 1024 * 1024
MAX_IMAGE_PIXELS = 20_000_000
MAX_VIBE_IMAGES = 5
MIN_SENTENCE_TRANSFORMERS = "6.1.0"
CATALOG_PATH = Path(__file__).parent / "data" / "vibe-style-catalog.json"


def normalize(vector: np.ndarray) -> np.ndarray:
    value = np.asarray(vector, dtype=np.float32).reshape(-1)
    norm = float(np.linalg.norm(value))
    if not np.isfinite(value).all() or not math.isfinite(norm) or norm <= 1e-12:
        raise ValueError("The embedding model returned an invalid vector")
    return value / norm


def bounded_download_progress(done: int | float, total: int | float) -> tuple[int, int]:
    """Return byte progress bounded by the known snapshot size."""
    total_bytes = max(0, int(total))
    return min(max(0, int(done)), total_bytes), total_bytes


def report_snapshot_progress(progress: Callable, description: str,
                             done: int | float, total: int | float) -> None:
    """Report reconstructed model bytes, ignoring transfer and file-count bars."""
    if not description.startswith("Reconstructing"):
        return
    done_bytes, total_bytes = bounded_download_progress(done, total)
    progress(done_bytes, total_bytes, description)


def vibe_runtime_status() -> dict:
    required_modules = ("sentence_transformers", "transformers", "torch", "torchvision",
                        "huggingface_hub", "PIL")
    missing = [module for module in required_modules
               if importlib.util.find_spec(module) is None]
    try:
        installed_version = metadata.version("sentence-transformers")
    except metadata.PackageNotFoundError:
        installed_version = None
    compatible_version = False
    if installed_version:
        from packaging.version import Version
        compatible_version = Version(installed_version) >= Version(MIN_SENTENCE_TRANSFORMERS)
    return {"installed_version": installed_version,
            "compatible": not missing and compatible_version,
            "missing": missing}


def load_catalog(path: Path = CATALOG_PATH) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict):
        data = data.get("entries")
    if not isinstance(data, list) or len(data) < 30:
        raise ValueError("The Vibe style catalog must contain at least 30 entries")
    seen = set()
    for item in data:
        if not all(isinstance(item.get(key), str) and item[key].strip()
                   for key in ("id", "visual", "style")):
            raise ValueError("Each Vibe catalog entry needs an id, visual description, and style")
        if item["id"] in seen:
            raise ValueError("Vibe catalog IDs must be unique")
        seen.add(item["id"])
    return data


def rank_catalog(image_vector: np.ndarray, catalog_vectors: np.ndarray,
                 catalog: list[dict]) -> dict:
    image = normalize(image_vector)
    matrix = np.asarray(catalog_vectors, dtype=np.float32)
    if matrix.ndim != 2 or len(matrix) != len(catalog) or matrix.shape[1] != image.size:
        raise ValueError("Image and catalog embedding dimensions do not match")
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    if not np.isfinite(matrix).all() or np.any(norms <= 1e-12):
        raise ValueError("The catalog contains an invalid embedding")
    similarities = (matrix / norms) @ image
    index = min(range(len(catalog)), key=lambda i: (-float(similarities[i]), catalog[i]["id"]))
    return catalog[index]


def blend_catalog(image_vectors, catalog_vectors, catalog):
    """Blend real image matches around a shared semantic direction."""
    vectors = np.asarray([normalize(vector) for vector in image_vectors], dtype=np.float32)
    if not 1 <= len(vectors) <= MAX_VIBE_IMAGES:
        raise ValueError("Choose between 1 and 5 images")
    matches = [rank_catalog(vector, catalog_vectors, catalog) for vector in vectors]
    primary = rank_catalog(vectors.mean(axis=0), catalog_vectors, catalog)
    textures = []
    seen = {primary["id"]}
    for match in matches:
        if match["id"] not in seen:
            seen.add(match["id"])
            for part in match["style"].rstrip(".").split(",")[1:3]:
                part = part.strip()
                if part and part.casefold() not in {text.casefold() for text in textures}:
                    textures.append(part)
    style = primary["style"]
    if textures:
        style = style.rstrip(".") + "; complementary textures: " + ", ".join(textures)
        style += "; cohesive arrangement, evolving instrumental layers, space between contrasting sections."
    pairs = [1 - float(vectors[i] @ vectors[j]) for i in range(len(vectors)) for j in range(i)]
    return {"id": primary["id"], "style": style,
            "entry_ids": [match["id"] for match in matches],
            "diversity": float(np.clip(np.mean(pairs), 0, 1)) if pairs else 0.0}


def validate_image(data: bytes):
    if not data or len(data) > MAX_IMAGE_BYTES:
        raise ValueError("Choose an image no larger than 10 MB")
    try:
        from PIL import Image, ImageOps
        with Image.open(io.BytesIO(data)) as image:
            if image.format not in {"JPEG", "PNG", "WEBP"}:
                raise ValueError("Use a JPG, PNG, or WebP image")
            if image.width * image.height > MAX_IMAGE_PIXELS:
                raise ValueError("The image is too large to analyze (maximum 20 megapixels)")
            image.verify()
        with Image.open(io.BytesIO(data)) as image:
            image = ImageOps.exif_transpose(image).convert("RGB")
            image.load()
            return image.copy()
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("The selected file is not a valid JPG, PNG, or WebP image") from error


class LocalEmbeddingRuntime:
    """Lazy offline-only model loader. One instance is held by VibeManager."""

    def __init__(self, model_path: Path):
        self.model_path = model_path
        self.model = None
        self.catalog_vectors = None
        self.catalog = None
        self._lock = threading.Lock()

    def _load(self, force_cpu=False):
        if self.model is not None:
            return
        runtime = vibe_runtime_status()
        if not runtime["compatible"]:
            version = runtime["installed_version"] or "not installed"
            raise RuntimeError(f"Vibe needs Sentence Transformers {MIN_SENTENCE_TRANSFORMERS} or newer; "
                               f"{version} is installed. Open Settings and select Update Vibe runtime.")
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from sentence_transformers import SentenceTransformer
        import torch
        devices = (["mps", "cpu"] if not force_cpu and torch.backends.mps.is_available() else ["cpu"])
        catalog = load_catalog()
        signature = hashlib.sha256((REVISION + CATALOG_PATH.read_bytes().decode() +
            "clustering-768-v1").encode()).hexdigest()
        cache_path = self.model_path.parent / f"catalog-{signature}.npy"
        last_error = None
        for device in devices:
            try:
                model = SentenceTransformer(str(self.model_path), device=device,
                    model_kwargs={"torch_dtype": torch.float32},
                    config_kwargs={"audio_config": None}, local_files_only=True)
                model.eval()
                vectors = None
                if cache_path.is_file():
                    try:
                        cached = np.load(cache_path, allow_pickle=False)
                        if cached.shape == (len(catalog), 768) and np.isfinite(cached).all():
                            vectors = np.asarray(cached, dtype=np.float32)
                    except (OSError, ValueError):
                        pass
                    if vectors is None:
                        cache_path.unlink(missing_ok=True)
                if vectors is None:
                    vectors = model.encode([row["visual"] for row in catalog], prompt_name="Clustering",
                        convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False)
                    vectors = np.asarray(vectors, dtype=np.float32)
                    cache_path.parent.mkdir(parents=True, exist_ok=True)
                    temp = cache_path.with_suffix(".tmp.npy")
                    np.save(temp, vectors, allow_pickle=False)
                    temp.replace(cache_path)
                if vectors.shape != (len(catalog), 768) or not np.isfinite(vectors).all():
                    cache_path.unlink(missing_ok=True)
                    raise ValueError("The local model produced an incompatible catalog embedding")
                self.model, self.catalog, self.catalog_vectors = model, catalog, vectors
                return
            except Exception as error:
                last_error = error
                if device != "mps":
                    raise
                if "model" in locals():
                    del model
                if hasattr(torch, "mps"):
                    torch.mps.empty_cache()
        raise last_error

    def _encode_image(self, image):
        try:
            return self.model.encode({"image": image}, convert_to_numpy=True,
                                          normalize_embeddings=True, show_progress_bar=False)
        except Exception:
            if not str(getattr(self.model, "device", "")).startswith("mps"):
                raise
            model, self.model = self.model, None
            self.catalog = self.catalog_vectors = None
            del model
            import torch
            torch.mps.empty_cache()
            self._load(force_cpu=True)
            return self.model.encode({"image": image}, convert_to_numpy=True,
                                          normalize_embeddings=True, show_progress_bar=False)

    def analyze(self, image) -> dict:
        return self.analyze_many([image])

    def analyze_many(self, images) -> dict:
        with self._lock:
            self._load()
            vectors = []
            for image in images:
                if len(vectors) >= MAX_VIBE_IMAGES:
                    raise ValueError("Choose up to 5 images")
                vectors.append(self._encode_image(image))
            return blend_catalog(vectors, self.catalog_vectors, self.catalog)

    def close(self):
        with self._lock:
            model, self.model = self.model, None
            self.catalog_vectors = None
            self.catalog = None
            if model is not None:
                try:
                    import torch
                    used_mps = str(getattr(model, "device", "")).startswith("mps")
                    del model
                    if used_mps and torch.backends.mps.is_available():
                        torch.mps.empty_cache()
                except Exception:
                    pass


class VibeManager:
    def __init__(self, root: Path | None = None, downloader: Callable | None = None):
        self.root = root or Path(os.environ.get("LUX_VIBE_DIR", Path.cwd() / "models" / "vibe"))
        self.model_path = self.root / REVISION
        self.state_path = Path.cwd() / ".lux" / "vibe" / "state.json"
        self.downloader = downloader or self._download_snapshot
        self.lock = threading.RLock()
        self.job = None
        self.runtime = None
        self._hash_verified_signature = None

    def _read_state(self):
        try:
            return json.loads(self.state_path.read_text())
        except (OSError, ValueError):
            return {}

    def status(self):
        with self.lock:
            state = self._read_state()
            runtime = vibe_runtime_status()
            return {"model_id": MODEL_ID, "revision": REVISION, "license": LICENSE_ID,
                "license_url": LICENSE_URL, "gemma_terms_url": GEMMA_TERMS_URL,
                "license_review_id": LICENSE_REVIEW_ID, "model_url": MODEL_URL,
                "license_accepted": (state.get("license") == LICENSE_ID
                    and state.get("license_review_id") == LICENSE_REVIEW_ID),
                "installed": self._verified(state),
                "runtime_compatible": runtime["compatible"],
                "runtime_version": runtime["installed_version"],
                "runtime_missing": runtime["missing"],
                "files_present": any(self.model_path.rglob("*.safetensors")),
                "job": dict(self.job) if self.job else None}

    def _verified(self, state=None):
        state = state or self._read_state()
        manifest = state.get("manifest")
        if (not state.get("ready") or state.get("revision") != REVISION
                or state.get("license_review_id") != LICENSE_REVIEW_ID or not manifest):
            return False
        for name, values in manifest.items():
            path = self.model_path / name
            if (not path.is_file() or path.stat().st_size != values.get("size")
                    or path.stat().st_mtime_ns != values.get("mtime_ns")):
                return False
        return bool(manifest)

    def _verify_hashes(self, state):
        manifest = state.get("manifest", {})
        files = [(name, self.model_path / name) for name in manifest]
        signature = tuple(sorted((name, path.stat().st_size, path.stat().st_mtime_ns)
                                 for name, path in files if path.is_file()))
        if len(signature) != len(manifest):
            return False
        if signature == self._hash_verified_signature:
            return True
        for name, path in files:
            digest = hashlib.sha256()
            with path.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest() != manifest[name].get("sha256"):
                return False
        self._hash_verified_signature = signature
        return True

    def start_install(self, license_review_id: str, accepted: bool):
        if license_review_id != LICENSE_REVIEW_ID or not accepted:
            raise ValueError("Review and accept the EmbeddingGemma license before downloading")
        with self.lock:
            if self.job and self.job.get("status") in {"queued", "running"}:
                return dict(self.job)
            job = {"id": uuid.uuid4().hex, "status": "queued", "stage": "queued",
                   "completed_bytes": 0, "total_bytes": 0}
            self.job = job
            threading.Thread(target=self._install, args=(job,), daemon=True).start()
            return dict(job)

    def _install(self, job):
        with self.lock:
            job.update(status="running", stage="downloading")
        runtime_updated = False
        try:
            job.update(stage="preparing_runtime")
            runtime = vibe_runtime_status()
            if not runtime["compatible"]:
                uv = shutil.which("uv")
                if not uv:
                    raise RuntimeError("Install uv, restart Lux, then update the Vibe runtime. Model files are already local.")
                job.update(stage="updating_runtime")
                prepared = subprocess.run([uv, "sync", "--frozen", "--extra", "vibe"],
                    cwd=Path(__file__).parent.parent,
                    capture_output=True, text=True, timeout=3600)
                if prepared.returncode:
                    raise RuntimeError("Could not update the local Vibe runtime. Check network access and disk space, then retry.")
                runtime_updated = True
                runtime = vibe_runtime_status()
                if not runtime["compatible"]:
                    job.update(stage="checking_runtime")
                    raise RuntimeError(f"Vibe needs Sentence Transformers {MIN_SENTENCE_TRANSFORMERS} or newer; "
                                        f"the installed version is {runtime['installed_version'] or 'missing'}. "
                                        "Update the Vibe runtime in Settings, then restart Lux.")
            job.update(stage="downloading")
            self.model_path.mkdir(parents=True, exist_ok=True)
            state = self._read_state()
            reuse_verified_files = self._verified(state) and self._verify_hashes(state)
            if reuse_verified_files:
                manifest = state["manifest"]
                total = sum(item["size"] for item in manifest.values())
                job.update(completed_bytes=total, total_bytes=total,
                           file="Verified local model files")
            else:
                manifest = self.downloader(self.model_path, lambda done, total, file:
                    job.update(completed_bytes=done, total_bytes=total, file=file))
            required = [p for p in self.model_path.rglob("*") if p.is_file()
                        and ".cache" not in p.parts and p.name != ".gitattributes"]
            if not required or not any(p.suffix in {".safetensors", ".bin"} for p in required):
                raise RuntimeError("The model download is incomplete: model weight files are missing")
            job.update(stage="verifying")
            verified = {}
            if reuse_verified_files:
                verified = manifest
            else:
                for path in required:
                    rel = str(path.relative_to(self.model_path))
                    digest = hashlib.sha256()
                    with path.open("rb") as handle:
                        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                            digest.update(chunk)
                    stat = path.stat()
                    verified[rel] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns,
                                     "sha256": digest.hexdigest()}
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
                self.state_path.write_text(json.dumps({"ready": True, "revision": REVISION,
                    "license": LICENSE_ID, "license_review_id": LICENSE_REVIEW_ID,
                    "manifest": verified}, indent=2))
            job.update(status="done", stage="restart_required" if runtime_updated else "done",
                       restart_required=runtime_updated,
                       completed_bytes=sum(x["size"] for x in verified.values()),
                       total_bytes=sum(x["size"] for x in verified.values()))
        except Exception as error:
            message = str(error)
            if job.get("stage") in {"preparing_runtime", "updating_runtime"}:
                message = "Could not prepare the local Vibe runtime. Check network access and disk space, then retry."
            elif job.get("stage") == "checking_runtime":
                message = str(error)
            elif any(marker in message.lower() for marker in ("gated", "401", "403", "access denied")):
                message = ("Hugging Face requires access to this model. Open the model page, accept its access terms, "
                           "sign in in Terminal with `hf auth login`, then retry.")
            else:
                message = "Model files could not be downloaded or verified. Check network access and Hugging Face model access, then retry."
            job.update(status="error", stage="error", error=message)

    @staticmethod
    def _download_snapshot(destination: Path, progress: Callable):
        from huggingface_hub import HfApi, snapshot_download
        # Snapshot contains the model artifacts only. No repository code is copied into Lux.
        from tqdm.auto import tqdm
        progress_lock = threading.Lock()
        model_info = HfApi().model_info(MODEL_ID, revision=REVISION, files_metadata=True)
        expected_total = sum(item.size or 0 for item in model_info.siblings
                             if item.rfilename and not item.rfilename.endswith(".md")
                             and item.rfilename != ".gitattributes")
        class ProgressBar(tqdm):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
            def update(self, n=1):
                result = super().update(n)
                # snapshot_download creates several kinds of bars: network bytes,
                # reconstructed bytes, and a file-count bar. Only reconstructed
                # bytes represent completed model files; summing all bars mixes
                # units and can display more than 100%.
                description = str(self.desc or "")
                if description.startswith("Reconstructing"):
                    with progress_lock:
                        report_snapshot_progress(progress, description, self.n, expected_total)
                return result
            def close(self):
                super().close()
        snapshot_download(repo_id=MODEL_ID, revision=REVISION, local_dir=str(destination),
                          tqdm_class=ProgressBar, ignore_patterns=["*.md", ".gitattributes"])
        files = [p for p in destination.rglob("*") if p.is_file() and ".cache" not in p.parts
                 and p.name != ".gitattributes"]
        total = sum(p.stat().st_size for p in files)
        progress(total, total, "Verifying model files")
        return files

    def analyze(self, image):
        return self.analyze_many([image])

    def analyze_many(self, images):
        state = self._read_state()
        if not self._verified(state) or not self._verify_hashes(state):
            raise RuntimeError("EmbeddingGemma is not installed. Open Settings to install it.")
        if self.runtime is None:
            with self.lock:
                if self.runtime is None:
                    self.runtime = LocalEmbeddingRuntime(self.model_path)
        return self.runtime.analyze_many(images)

    def release(self):
        with self.lock:
            runtime, self.runtime = self.runtime, None
        if runtime:
            runtime.close()


_manager = None
_manager_lock = threading.Lock()


def get_vibe_manager() -> VibeManager:
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = VibeManager()
        return _manager
