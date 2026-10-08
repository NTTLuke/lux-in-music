"""Regenerate a section of a song with YuE2 semantic tokens (used to edit a piece of one stem).

How it works (see vendor/audio.cpp/docs/models/yue2.md, "Continuing From Semantic Tokens"):
  1. get the song's semantic tokens S (25 per second): saved at generation time, or
     recovered by re-running the original request with stop_after=semantic (deterministic)
  2. force S[:A] as history and let the model sample frames A..B with a new seed
  3. splice tokens: new[:B] + S[B:], render the whole song once (one coherent acoustic pass)
  4. keep the original audio outside [A, B] and crossfade the new render in at the edges
"""

import base64
import io
import json
import time
import wave
from pathlib import Path

import httpx
import numpy as np

from . import engine
from .params import GenerationParams

FPS = 25                 # semantic frames per second
SR = 48000               # YuE2 output sample rate
XFADE_S = 0.2            # crossfade at each edge of the replaced region


def _run(lyrics: str, seed: int, options: dict) -> dict:
    body = {"model": engine.MODEL_ID, "request": {"lyrics": lyrics, "seed": seed, "options": options}}
    r = httpx.post(f"{engine.ENGINE_URL}/v1/tasks/run", json=body, timeout=httpx.Timeout(10, read=None))
    if r.status_code != 200:
        raise RuntimeError(f"audio.cpp error {r.status_code}: {r.text[:400]}")
    return r.json()


def _semantic(data: dict) -> list[int]:
    for art in data.get("artifacts", []):
        if art["id"] == "semantic":
            return json.loads(base64.b64decode(art["payload"]))
    raise RuntimeError("engine returned no semantic tokens")


def _pcm(wav_bytes: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, w.getnchannels())
    return x.astype(np.float32) / 32768.0


def _wav(x: np.ndarray) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(x.shape[1]); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


def _base_options(meta: dict) -> dict:
    """Request options of the original generation, plus its score when it was planned."""
    params = GenerationParams(**meta["params"])
    options = params.to_request()["options"]
    options.pop("semantic_min_tokens", None)
    options.pop("semantic_max_tokens", None)
    if params.cot != "off" and not params.abc:
        score = meta.get("artifacts", {}).get("score")
        if not score:
            raise RuntimeError("this song was planned (cot=%s) but its score is missing" % params.cot)
        options["abc"] = (engine.OUTPUT_DIR / score).read_text()
    return options


def song_tokens(song: str) -> list[int]:
    """Semantic tokens of a song, recovering (and caching) them when they were not exported."""
    cache = engine.OUTPUT_DIR / f"{song}.semantic.json"
    if cache.exists():
        return json.loads(cache.read_text())
    meta = json.loads((engine.OUTPUT_DIR / f"{song}.json").read_text())
    if meta.get("parent"):
        raise RuntimeError("edited song has no saved tokens")
    params = GenerationParams(**meta["params"])
    # Same request as the original, stopped after the semantic stage: same seed, same tokens.
    options = {**params.to_request()["options"], "stop_after": "semantic"}
    tokens = _semantic(_run(params.lyrics, params.seed, options))
    expected = meta["duration_s"] * FPS
    if abs(len(tokens) - expected) > 2:
        raise RuntimeError(f"recovered {len(tokens)} tokens but the song has {expected:.0f} frames")
    cache.write_text(json.dumps(tokens))
    return tokens


def crossfade_region(orig: np.ndarray, new: np.ndarray, sa: int, sb: int, xf: int) -> np.ndarray:
    """orig outside [sa, sb), new inside, equal-power crossfades of xf samples at the edges."""
    length = len(orig)
    w = np.zeros(length, dtype=np.float32)
    w[sa:sb] = 1.0
    ramp = np.sin(np.linspace(0, np.pi / 2, xf, dtype=np.float32)) ** 2
    if sa - xf // 2 > 0:                 # fade in, unless the region starts at the top
        w[sa - xf // 2:sa - xf // 2 + xf] = ramp
    if sb + xf // 2 < length:            # fade back out, unless it runs to the end
        w[sb - xf // 2:sb - xf // 2 + xf] = ramp[::-1]
    else:
        w[sb:] = 1.0
    return orig * np.sqrt(1 - w)[:, None] + new * np.sqrt(w)[:, None]


def render_section(song: str, start_s: float, end_s: float, seed: int, lyrics: str | None = None) -> tuple[np.ndarray, dict]:
    """New take of [start_s, end_s) of a song; returns the composite audio (48 kHz) and edit info."""
    meta = json.loads((engine.OUTPUT_DIR / f"{song}.json").read_text())
    tokens = song_tokens(song)
    n = len(tokens)
    a = max(1, int(round(start_s * FPS)))
    b = min(n, int(round(end_s * FPS)))
    if b - a < FPS:
        raise ValueError("select at least 1 second")

    lyrics = lyrics if lyrics and lyrics.strip() else meta["params"]["lyrics"]
    options = _base_options(meta)
    t0 = time.time()

    # 2. new take of the selection, conditioned on everything before it
    leg = _semantic(_run(lyrics, seed, {**options, "semantic_prefix": json.dumps(tokens[:a]),
                                        "semantic_min_tokens": str(b), "semantic_max_tokens": str(b),
                                        "stop_after": "semantic"}))
    spliced = leg[:b] + tokens[b:]

    # 3. one acoustic pass over the whole spliced song (original seed keeps the NAR noise)
    data = _run(lyrics, meta["params"]["seed"], {**options, "semantic_prefix": json.dumps(spliced),
                                                  "semantic_min_tokens": str(n), "semantic_max_tokens": str(n)})
    new = _pcm(base64.b64decode(data["audio"]))

    # 4. original audio outside the region, new render inside
    orig = _pcm((engine.OUTPUT_DIR / f"{song}.wav").read_bytes())
    length = min(len(orig), len(new))
    out = crossfade_region(orig[:length], new[:length], int(a / FPS * SR), int(b / FPS * SR), int(XFADE_S * SR))
    info = {"meta": meta, "lyrics": lyrics, "spliced": spliced, "start_s": round(a / FPS, 2), "end_s": round(b / FPS, 2),
            "seed": seed, "elapsed_s": round(time.time() - t0, 1)}
    return out, info
