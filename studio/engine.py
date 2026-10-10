"""Shared generation and artifact storage, using the job's selected provider."""

import array
import base64
import json
import os
import io
import re
import time
import wave
from dataclasses import dataclass, field
from pathlib import Path

from .params import GenerationParams
from .models import get_manager
from .providers import get_provider

OUTPUT_DIR = Path(os.environ.get("STUDIO_OUTPUT_DIR", Path(__file__).resolve().parent.parent / "outputs"))


@dataclass
class GenerationResult:
    wav_path: Path
    meta_path: Path
    duration_s: float
    elapsed_s: float
    sample_rate: int
    channels: int
    artifacts: dict[str, Path] = field(default_factory=dict)


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40] or "song"


def auto_title(lyrics: str) -> str:
    """Use a short lyric phrase as the title, preferring the chorus hook."""
    lines = [l.strip() for l in lyrics.splitlines()]
    try:
        start = next(i for i, l in enumerate(lines) if l.lower().startswith("[chorus"))
    except StopIteration:
        start = 0
    for l in lines[start:] + lines[:start]:
        if l and not l.startswith("["):
            clause = re.split(r"[,.;:!?\u2014]", l)[0]
            words = re.sub(r"[^\w\s'-]", "", clause).split()[:6]
            return " ".join(words).title() or "Untitled"
    return "Untitled"


def compute_peaks(wav_path: Path, buckets: int = 160, normalize: bool = True) -> list[float]:
    """Peak per bucket (0..1) for drawing waveforms in the UI.

    normalize=True scales the loudest bucket to 1 (song thumbnails); False keeps the
    absolute level, so stems show their real loudness relative to each other.
    """
    with wave.open(str(wav_path)) as w:
        samples = array.array("h", w.readframes(w.getnframes()))
    step = max(1, len(samples) // buckets)
    peaks = [max(map(abs, samples[i:i + step:4]), default=0) for i in range(0, step * buckets, step)]
    top = (max(peaks, default=0) or 1) if normalize else 32768
    return [round(p / top, 3) for p in peaks]


def health() -> dict:
    status = get_manager().status()
    return {"engine": "ok" if status["active"] else "down",
            "backend": status["active"]["validation"]["backend"] if status["active"] else None,
            "setup_required": status["setup_required"]}


def generate(params: GenerationParams, name: str | None = None, profile: dict | None = None) -> GenerationResult:
    profile = get_manager().snapshot(profile)
    provider = get_provider(profile)
    adapter = provider.adapter(profile)
    normalized = adapter.normalize(params)
    request = adapter.request(params)
    t0 = time.time()
    data = provider.run(profile, request)
    elapsed = time.time() - t0
    if "audio" not in data:
        raise RuntimeError(f"no audio in response: {list(data)}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    title = params.title or auto_title(params.lyrics)
    stem = name or f"{time.strftime('%Y%m%d-%H%M%S')}-{slugify(title)}"
    wav_path = OUTPUT_DIR / f"{stem}.wav"
    wav = base64.b64decode(data["audio"])
    wav_path.write_bytes(wav)

    with wave.open(io.BytesIO(wav)) as audio:
        sr, ch = audio.getframerate(), audio.getnchannels()
        duration = audio.getnframes() / sr

    artifacts = {}
    artifact_meta = {}
    for art in data.get("artifacts", []):
        ext = {"score": "abc", "semantic": "semantic.json"}.get(art["id"], "bin")
        p = OUTPUT_DIR / f"{stem}.{ext}"
        p.write_bytes(base64.b64decode(art["payload"]))
        artifacts[art["id"]] = p
        artifact_meta[art["id"]] = art.get("meta", {})

    meta_path = OUTPUT_DIR / f"{stem}.json"
    meta_path.write_text(json.dumps({
        "name": stem,
        "title": title,
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "params": normalized.model_dump(exclude_none=True),
        "model_profile": profile,
        "duration_s": round(duration, 2),
        "elapsed_s": round(elapsed, 1),
        "sample_rate": sr,
        "channels": ch,
        "artifacts": {k: v.name for k, v in artifacts.items()},
        "artifact_meta": artifact_meta,
        "peaks": compute_peaks(wav_path),
    }, indent=2))
    return GenerationResult(wav_path, meta_path, duration, elapsed, sr, ch, artifacts)
