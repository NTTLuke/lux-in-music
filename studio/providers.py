"""Runtime boundary. Shared jobs use provider instances and immutable profiles."""

import atexit
import base64
import io
import json
import hashlib
import os
import platform
import socket
import subprocess
import threading
import time
import wave
from contextlib import contextmanager
from pathlib import Path
from typing import Protocol

import httpx

from .adapters.yue2 import YuE2Adapter

ROOT = Path(__file__).resolve().parent.parent
AUDIOCPP_REVISION = "6c3ab9ad4e599a44d287697863b4f8846ef658be"


class Provider(Protocol):
    def adapter(self, profile: dict): ...
    def run(self, profile: dict, request: dict) -> dict: ...
    def probe(self, profile: dict, cancel=None) -> dict: ...
    def close(self) -> None: ...


def runtime_binary() -> Path:
    default = ROOT / "vendor/audio.cpp/build" / (
        "macos-metal-release" if platform.system() == "Darwin" else "cpu-release"
    ) / "bin/audiocpp_server"
    return Path(os.environ.get("AUDIOCPP_BINARY", default)).resolve()


class AudioCppProvider:
    def __init__(self, state_dir: Path | None = None):
        self.state_dir = state_dir or Path(os.environ.get("LUX_STATE_DIR", ROOT / ".lux"))
        self.backend = os.environ.get("LUX_BACKEND", "metal" if platform.system() == "Darwin" else "cpu")
        self.lock = threading.RLock()
        self.slots = {}  # generation and optional separation runtimes are independent
        self.closing = False

    def adapter(self, profile):
        if profile["family"] == "yue2":
            return YuE2Adapter()
        raise ValueError(f"No generation adapter for {profile['family']}")

    def compatibility_token(self):
        binary = runtime_binary()
        fingerprint = (str(binary), binary.stat().st_size, binary.stat().st_mtime_ns) if binary.exists() else None
        return hashlib.sha256(repr((self.backend, platform.system(), platform.machine(), fingerprint)).encode()).hexdigest()

    def _stop(self, slot):
        entry = self.slots.pop(slot, None)
        if not entry:
            return
        process = entry["process"]
        if process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        entry["log"].close()

    def _start(self, profile):
        if self.closing:
            raise RuntimeError("The studio is shutting down")
        slot = "generation" if profile["task"] == "gen" else "separation"
        identity = (profile["id"], profile["revision"], profile["root"])
        current = self.slots.get(slot)
        if current and current["identity"] == identity and current["process"].poll() is None:
            return current
        self._stop(slot)
        binary = runtime_binary()
        if not binary.is_file():
            raise RuntimeError("audio.cpp is not installed. Run ./studio.sh to prepare the software.")
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        directory = self.state_dir / "runtime"
        directory.mkdir(parents=True, exist_ok=True)
        model_config = self.adapter(profile).runtime_config(profile) if profile["task"] == "gen" else {
            "path": str(Path(profile["root"]) / profile["main_file"]), "session_options": {}}
        config = {"host": "127.0.0.1", "port": port, "backend": self.backend,
                  "device": 0, "threads": min(os.cpu_count() or 8, 8), "lazy_load": True,
                  "model_spec_override": str(ROOT / "vendor/audio.cpp/model_specs"),
                  "models": [{"id": profile["id"], "family": profile["family"],
                              "task": profile["task"], "mode": "offline", **model_config}]}
        config_path = directory / f"{slot}.json"
        config_path.write_text(json.dumps(config, indent=2))
        log_path = directory / f"{slot}.log"
        log = log_path.open("ab")
        process = subprocess.Popen([str(binary), "--config", str(config_path), "--no-ui", "--busy-timeout-ms", "0"],
                                   stdout=log, stderr=subprocess.STDOUT)
        entry = {"identity": identity, "process": process, "url": f"http://127.0.0.1:{port}", "log": log}
        self.slots[slot] = entry
        if self.closing:
            self._stop(slot)
            raise RuntimeError("The studio is shutting down")
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if process.poll() is not None:
                self._stop(slot)
                raise RuntimeError(f"audio.cpp failed to start. Details: {log_path}")
            try:
                response = httpx.get(entry["url"] + "/health", timeout=1)
                if response.is_success:
                    return entry
            except httpx.HTTPError:
                pass
            time.sleep(0.1)
        self._stop(slot)
        raise RuntimeError(f"audio.cpp startup timed out. Details: {log_path}")

    @contextmanager
    def _lease(self, cancel=None):
        from .models import Cancelled
        while not self.lock.acquire(timeout=0.1):
            if cancel and cancel.is_set():
                raise Cancelled()
        try:
            if cancel and cancel.is_set():
                raise Cancelled()
            yield
        finally:
            self.lock.release()

    def run(self, profile, request, cancel=None):
        # Hold through inference: activation cannot restart an engine in use.
        with self._lease(cancel):
            entry = self._start(profile)
            response = httpx.post(entry["url"] + "/v1/tasks/run",
                                  json={"model": profile["id"], "request": request},
                                  timeout=httpx.Timeout(10, read=None))
            if not response.is_success:
                raise RuntimeError(f"audio.cpp error {response.status_code}: {response.text[:500]}")
            return response.json()

    def probe(self, profile, cancel=None):
        if profile["task"] == "gen":
            request = self.adapter(profile).smoke_request()
        else:
            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as audio:
                audio.setnchannels(2)
                audio.setsampwidth(2)
                audio.setframerate(48000)
                audio.writeframes(b"\0" * 48000 * 2 * 2)
            request = {"audio_base64": base64.b64encode(buffer.getvalue()).decode(), "seed": 1234}
            if profile["family"] == "sam_audio":
                request["text"] = "voice"
        data = self.run(profile, request, cancel)
        payload = data.get("audio") or next(iter(data.get("named_audio_outputs", [])), {}).get("audio")
        if not payload:
            raise RuntimeError("The model test returned no audio. The previous selection is preserved.")
        with wave.open(io.BytesIO(base64.b64decode(payload))) as audio:
            if not audio.getnframes():
                raise RuntimeError("The model test returned empty audio.")
        # An externally supplied binary may not match the supported source pin.
        revision = None
        if not os.environ.get("AUDIOCPP_BINARY"):
            try:
                revision = subprocess.check_output(["git", "-C", str(ROOT / "vendor/audio.cpp"), "rev-parse", "HEAD"],
                                                   text=True, stderr=subprocess.DEVNULL, timeout=2).strip()
            except (OSError, subprocess.SubprocessError):
                pass
        return {"backend": self.backend, "runtime": "audio.cpp", "runtime_revision": revision,
                "supported_runtime_revision": AUDIOCPP_REVISION, "runtime_binary": str(runtime_binary()),
                "compatibility_token": self.compatibility_token(),
                "tested_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "smoke_test": "audio"}

    def close(self):
        # Stop owned processes even if a worker is blocked in an inference call.
        self.closing = True
        for slot in list(self.slots):
            self._stop(slot)


_providers: dict[str, Provider] = {"audio.cpp": AudioCppProvider()}


def register_provider(name: str, provider: Provider):
    """Allow another runtime to implement the shared generation contract."""
    _providers[name] = provider


def get_provider(profile: dict) -> Provider:
    try:
        return _providers[profile["provider"]]
    except KeyError:
        raise ValueError(f"Provider {profile.get('provider')} is not configured") from None


def close_providers():
    for provider in _providers.values():
        provider.close()


atexit.register(close_providers)


def main():
    import argparse
    from .models import get_manager
    parser = argparse.ArgumentParser(description="Serve the model selected in Lux Settings")
    parser.add_argument("--serve-active", action="store_true", required=True)
    parser.parse_args()
    try:
        profile = get_manager().snapshot()
        provider = get_provider(profile)
        with provider.lock:
            entry = provider._start(profile)
        print(f"Selected profile {profile['id']} is served at {entry['url']}", flush=True)
        entry["process"].wait()
    finally:
        close_providers()


if __name__ == "__main__":
    main()
