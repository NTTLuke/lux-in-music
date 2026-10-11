"""Pinned model catalog, licensed downloads, verification, and profile storage."""

import copy
import hashlib
import json
import os
import shutil
import threading
import time
import uuid
from pathlib import Path

import httpx

from .providers import ROOT, get_provider


class SetupRequired(ValueError):
    pass


class Cancelled(Exception):
    pass


class ModelManager:
    def __init__(self, state_dir=None, models_dir=None, catalog=None, client=None):
        self.state_dir = Path(state_dir or os.environ.get("LUX_STATE_DIR", ROOT / ".lux"))
        self.models_dir = Path(models_dir or os.environ.get("LUX_MODELS_DIR", ROOT / "models")).resolve()
        source = catalog if catalog is not None else json.loads((ROOT / "config/model-catalog.json").read_text())["models"]
        self.catalog = {model["id"]: model for model in source}
        self.client = client or (lambda: httpx.Client(follow_redirects=True, timeout=30))
        self.lock = threading.RLock()
        self.jobs = {}
        self.events = {}
        self.claims = {}  # job_id -> (model_id, file paths) for running setups
        self.threads = []
        self.state_error = None
        try:
            self.state = json.loads((self.state_dir / "settings.json").read_text())
            if not isinstance(self.state, dict) or self.state.get("schema_version") != 1 or any(
                not isinstance(self.state.get(key), dict) for key in ("profiles", "verified", "separators")
            ):
                raise ValueError("Unsupported settings format")
        except FileNotFoundError:
            self.state = {"schema_version": 1, "active": None, "separators": {}, "profiles": {}, "verified": {}}
        except (ValueError, OSError) as error:
            self.state_error = f"Settings could not be read: {error}. Restore .lux/settings.json before saving."
            self.state = {"schema_version": 1, "active": None, "separators": {}, "profiles": {}, "verified": {}}

    def _save(self):
        if self.state_error:
            raise SetupRequired(self.state_error)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        temp = self.state_dir / "settings.json.tmp"
        temp.write_text(json.dumps(self.state, indent=2) + "\n")
        temp.replace(self.state_dir / "settings.json")

    def profile(self, model_id, precision=None, vae_precision=None):
        if model_id not in self.catalog:
            raise ValueError("Unknown model")
        model = self.catalog[model_id]
        external = model.get("delivery", "local") == "external"
        precision = precision or model["default_precision"]
        vae_precision = vae_precision or model.get("default_vae")
        if external and (precision or vae_precision):
            raise ValueError("This provider manages precision and VAE remotely")
        if not external and (precision not in model["precisions"] or (model["vaes"] and vae_precision not in model["vaes"])):
            raise ValueError("Unsupported precision. BF16 and FP16 are different formats.")
        if not model["vaes"] and vae_precision:
            raise ValueError("This model does not have a configurable VAE")
        files = [] if external else [model["precisions"][precision], *model["required"]]
        if vae_precision:
            files.append(model["vaes"][vae_precision])
        review = {"model": model_id, "revision": model["revision"], "licenses": model["licenses"]}
        review_id = hashlib.sha256(json.dumps(review, sort_keys=True).encode()).hexdigest()
        profile = {"id": f"{model_id}--{precision or 'external'}" + (f"--{vae_precision}" if vae_precision else ""),
                "model_id": model_id, "name": model["name"], "provider": model["provider"],
                "family": model["family"], "task": model["task"], "mode_id": model.get("mode_id"),
                "revision": model["revision"], "precision": precision, "vae_precision": vae_precision,
                "delivery": "external" if external else "local",
                "root": None if external else str(self.models_dir / model["install_dir"] / "releases" / model["revision"]),
                "legacy_root": None if external else str(self.models_dir / model["install_dir"]), "files": copy.deepcopy(files),
                "main_file": None if external else model["precisions"][precision]["path"],
                "vae_file": model["vaes"][vae_precision]["path"] if vae_precision else None,
                "licenses": copy.deepcopy(model["licenses"]), "license_review_id": review_id}
        if model.get("input_audio"):
            profile["input_audio"] = copy.deepcopy(model["input_audio"])
        profile["capabilities"] = copy.deepcopy(get_provider(profile).adapter(profile).capabilities) if profile["task"] == "gen" else {"separation": True}
        return profile

    @staticmethod
    def fingerprint(path):
        stat = path.stat()
        return {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns, "inode": stat.st_ino}

    def file_status(self, profile, file):
        path = Path(profile["root"]) / file["path"]
        if not path.is_file() and profile.get("legacy_root"):
            path = Path(profile["legacy_root"]) / file["path"]
        if not path.is_file() or path.stat().st_size != file["size"]:
            return "missing"
        cached = self.state["verified"].get(str(path), {})
        expected = file.get("sha256") or file.get("git_sha1")
        return "verified" if cached.get("fingerprint") == self.fingerprint(path) and cached.get("hash") == expected else "installed"

    def is_verified(self, profile):
        return all((Path(profile["root"]) / f["path"]).is_file() and self.file_status(profile, f) == "verified" for f in profile["files"])

    def ready(self, profile):
        if not profile or not profile.get("validation") or not self.is_verified(profile):
            return False
        try:
            token = getattr(get_provider(profile), "compatibility_token", None)
            return not token or profile["validation"].get("compatibility_token") == token()
        except (ValueError, OSError):
            return False

    def verified_profile(self, profile):
        saved = self.state["profiles"].get(profile["id"])
        keys = ("revision", "provider", "family", "task", "precision", "vae_precision", "root",
                "main_file", "vae_file", "files")
        if not saved or any(saved.get(key) != profile.get(key) for key in keys):
            return None
        if saved.get("input_audio") and saved["input_audio"] != profile.get("input_audio"):
            return None
        return saved if self.ready(saved) else None

    def status(self):
        with self.lock:
            active = self.state["profiles"].get(self.state.get("active"))
            ready = self.ready(active)
            current = copy.deepcopy(active) if ready else None
            if current:
                current["capabilities"] = copy.deepcopy(get_provider(current).adapter(current).capabilities)
            return {"active": current, "setup_required": not ready,
                    "state_error": self.state_error, "separators": copy.deepcopy(self.state["separators"]),
                    "accepted_license_reviews": list(self.state.get("license_reviews", {})),
                    "profiles": [{"id": p["id"], "capabilities": p.get("capabilities", {}), "ready": self.ready(p)} for p in self.state["profiles"].values()],
                    "jobs": [copy.deepcopy(job) for job in self.jobs.values()]}

    def options(self):
        result = []
        for model in self.catalog.values():
            choices = []
            for precision in model["precisions"] or [None]:
                for vae in model["vaes"] or [None]:
                    profile = self.profile(model["id"], precision, vae)
                    states = [self.file_status(profile, file) for file in profile["files"]]
                    choices.append({"id": profile["id"], "precision": precision, "vae_precision": vae,
                                    "bytes": sum(f["size"] for f in profile["files"]),
                                    "missing_bytes": sum(f["size"] for f, state in zip(profile["files"], states) if state == "missing"),
                                    "installed": "missing" not in states,
                                    "ready": bool(self.verified_profile(profile)),
                                    "license_review_id": profile["license_review_id"]})
            result.append({**{k: model[k] for k in ("id", "name", "description", "provider", "task", "revision", "licenses", "default_precision", "default_vae")},
                           "delivery": model.get("delivery", "local"), "choices": choices})
        return result

    def snapshot(self, profile=None):
        with self.lock:
            profile = profile or self.state["profiles"].get(self.state.get("active"))
            if not self.ready(profile):
                raise SetupRequired("Choose, verify, and activate a model in Settings first.")
            current = copy.deepcopy(profile)
            if current["task"] == "gen":
                current["capabilities"] = copy.deepcopy(get_provider(current).adapter(current).capabilities)
            return current

    def separator(self, mode):
        profile = self.state["profiles"].get(self.state["separators"].get(mode))
        if not profile:
            raise SetupRequired("Set up this optional separation model in Settings first.")
        return self.snapshot(profile)

    def song_profile(self, meta):
        profile = meta.get("model_profile")
        if profile:
            return self.snapshot(profile)
        # Migration for pre-profile songs: they were rendered with Q8_0/F16 YuE2.
        legacy_id = self.profile("yue2-3b", "q8_0", "f16")["id"]
        profile = self.state["profiles"].get(legacy_id)
        if not profile:
            raise SetupRequired("This older song needs YuE2 Q8_0 + VAE F16. Verify that profile in Settings to edit it.")
        return self.snapshot(profile)

    def _verify(self, profile, file, path, event, job):
        if path.stat().st_size != file["size"]:
            raise ValueError(f"Incomplete file: {file['path']}")
        digest = hashlib.sha256() if file.get("sha256") else hashlib.sha1(b"blob " + str(file["size"]).encode() + b"\0")
        self._update(job, stage="verifying", file=file["path"])
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
                if event.is_set():
                    raise Cancelled()
                digest.update(chunk)
        if digest.hexdigest() != (file.get("sha256") or file.get("git_sha1")):
            raise ValueError(f"Checksum mismatch: {file['path']}. Retry to download a verified copy.")

    def _download(self, profile, file, event, job):
        path = Path(profile["root"]) / file["path"]
        self._adopt(profile, file, path, event, job)
        if path.is_file():
            try:
                self._verify(profile, file, path, event, job)
                return path
            except ValueError:
                pass  # keep the old file until a verified replacement is ready
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_name(path.name + ".part")
        offset = partial.stat().st_size if partial.exists() else 0
        if offset > file["size"]:
            partial.unlink()
            offset = 0
        self._update(job, stage="downloading", file=file["path"], file_bytes=offset, file_total=file["size"])
        if offset < file["size"]:
            headers = {"Accept-Encoding": "identity"}
            if offset:
                headers["Range"] = f"bytes={offset}-"
            with self.client() as client:
                with client.stream("GET", file["url"], headers=headers) as response:
                    response.raise_for_status()
                    if response.status_code == 206:
                        content_range = response.headers.get("Content-Range", "")
                        if not content_range.startswith(f"bytes {offset}-") or not content_range.endswith(f"/{file['size']}"):
                            partial.unlink(missing_ok=True)
                            raise ValueError("The server returned an invalid download range. Retry the download.")
                    else:
                        offset = 0  # server ignored Range; restart rather than append
                    with partial.open("ab" if offset else "wb") as stream:
                        for chunk in response.iter_bytes(1024 * 1024):
                            if event.is_set():
                                raise Cancelled()
                            stream.write(chunk)
                            offset += len(chunk)
                            self._update(job, file_bytes=offset)
                            if offset > file["size"]:
                                raise ValueError("Downloaded file exceeds its published size")
        try:
            self._verify(profile, file, partial, event, job)
        except ValueError:
            if partial.stat().st_size == file["size"]:
                partial.unlink()  # a full corrupt partial cannot be resumed
            raise
        partial.replace(path)
        return path

    def _adopt(self, profile, file, path, event, job):
        """Reuse legacy files after verification, without overwriting their releases."""
        old = Path(profile.get("legacy_root", profile["root"])) / file["path"]
        if path.exists() or not old.is_file() or old == path:
            return
        try:
            self._verify(profile, file, old, event, job)
        except ValueError:
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(old, path)
        except OSError:
            if shutil.disk_usage(path.parent).free < file["size"] + 64 * 1024 * 1024:
                raise ValueError("Not enough space to import existing model files")
            shutil.copyfile(old, path)

    def start(self, model_id, precision, vae_precision, review_id, accepted, download=True):
        profile = self.profile(model_id, precision, vae_precision)
        if not accepted or review_id != profile["license_review_id"] or not profile["licenses"] or any(not l.get("verified") or not l.get("id") or not l.get("url") for l in profile["licenses"]):
            raise ValueError("Review and accept the displayed licenses for this release before continuing.")
        with self.lock:
            if self.state_error:
                raise SetupRequired(self.state_error)
            paths = {str(Path(profile["root"]) / f["path"]) for f in profile["files"]}
            for job_id, (other_model, other_paths) in self.claims.items():
                if self.jobs[job_id]["status"] in {"queued", "running"} and (other_model == model_id or paths & other_paths):
                    raise ValueError("A setup using these model files is running. Wait or cancel it first.")
            profile["license_accepted_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
            self.state.setdefault("license_reviews", {})[review_id] = {
                "accepted_at": profile["license_accepted_at"], "model_id": model_id,
                "revision": profile["revision"], "licenses": copy.deepcopy(profile["licenses"])}
            self._save()  # acknowledge this exact release before transferring any file
            job_id = uuid.uuid4().hex[:10]
            job = {"id": job_id, "profile_id": profile["id"], "status": "queued", "stage": "queued",
                   "created": time.time(), "total_bytes": sum(f["size"] for f in profile["files"]), "completed_bytes": 0}
            self.jobs[job_id] = job
            self.claims[job_id] = (model_id, paths)
            event = self.events[job_id] = threading.Event()
            thread = threading.Thread(target=self._work, args=(job, profile, event, download), daemon=True)
            self.threads.append(thread)
            thread.start()
            return copy.deepcopy(job)

    def _update(self, job, **changes):
        with self.lock:
            job.update(changes)

    def _work(self, job, profile, event, download):
        try:
            self._update(job, status="running")
            with self.lock:
                saved = self.verified_profile(profile) if not download else None
                if saved:
                    profile["validation"] = copy.deepcopy(saved["validation"])
            if not saved:
                self._prepare_files_and_probe(job, profile, event, download)
            if event.is_set():
                raise Cancelled()
            with self.lock:
                previous = self.state
                self.state = copy.deepcopy(previous)
                try:
                    self.state["profiles"][profile["id"]] = profile
                    if profile["task"] == "gen":
                        self.state["active"] = profile["id"]
                    else:
                        self.state["separators"][profile["mode_id"]] = profile["id"]
                    self._save()
                except Exception:
                    self.state = previous
                    raise
            self._update(job, status="done", stage="ready", completed_bytes=job["total_bytes"])
        except Cancelled:
            self._update(job, status="cancelled", stage="cancelled")
        except Exception as error:
            self._update(job, status="error", stage="error", error=str(error))
        finally:
            self._update(job, finished=time.time())

    def _prepare_files_and_probe(self, job, profile, event, download):
        if profile["files"]:
            self.models_dir.mkdir(parents=True, exist_ok=True)
        remaining = sum(f["size"] for f in profile["files"] if self.file_status(profile, f) == "missing")
        # ponytail: free space is checked per job, so parallel setups can overcommit; a full disk fails the
        # download and leaves a resumable .part. Reserve other jobs' missing bytes if this bites.
        if download and profile["files"] and shutil.disk_usage(self.models_dir).free < remaining + 64 * 1024 * 1024:
            raise ValueError("Not enough disk space for these model files")
        for file in profile["files"]:
            if event.is_set():
                raise Cancelled()
            path = Path(profile["root"]) / file["path"]
            self._adopt(profile, file, path, event, job)
            if download:
                path = self._download(profile, file, event, job)
            elif not path.is_file():
                raise ValueError("Required files are missing. Download this profile first.")
            else:
                self._verify(profile, file, path, event, job)
            with self.lock:
                self.state["verified"][str(path)] = {"fingerprint": self.fingerprint(path), "hash": file.get("sha256") or file.get("git_sha1")}
                self._save()
            self._update(job, completed_bytes=job["completed_bytes"] + file["size"], file_bytes=0)
        self._update(job, stage="testing", file=None)
        if event.is_set():
            raise Cancelled()
        profile["validation"] = get_provider(profile).probe(profile, cancel=event)

    def cancel(self, job_id):
        if job_id not in self.events:
            raise ValueError("Unknown model setup job")
        self.events[job_id].set()

    def close(self):
        for event in self.events.values():
            event.set()


_manager = None
_manager_lock = threading.Lock()


def get_manager():
    global _manager
    with _manager_lock:
        if _manager is None:
            _manager = ModelManager()
    return _manager
