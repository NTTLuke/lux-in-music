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
MAX_SAME_TOKENS = 0.5    # a take sharing more than this share of tokens with the original is re-rolled
MAX_REROLLS = 3


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


def render_section(song: str, start_s: float, end_s: float, seed: int, lyrics: str | None = None,
                   variation: str = "new") -> tuple[np.ndarray, dict]:
    """New take of [start_s, end_s) of a song; returns the composite audio (48 kHz) and edit info.

    variation="new"   regenerate without the song's score: same history, freshly written notes
                      (measured on the vocal line: melody similarity 0.53-0.63, like two different
                      parts of the same song, vs 0.94 when the score is kept)
    variation="same"  keep the score: the same notes re-sung, only the performance/timbre changes
    """
    meta = json.loads((engine.OUTPUT_DIR / f"{song}.json").read_text())
    tokens = song_tokens(song)
    n = len(tokens)
    a = max(1, int(round(start_s * FPS)))
    b = min(n, int(round(end_s * FPS)))
    if b - a < FPS:
        raise ValueError("select at least 1 second")

    lyrics = lyrics if lyrics and lyrics.strip() else meta["params"]["lyrics"]
    options = _base_options(meta)
    if variation == "new" and "abc" in options:
        # The score fixes melody and rhythm; drop it so the model writes the selection anew.
        options = {k: v for k, v in options.items() if k not in ("abc", "cot")} | {"cot": "off"}
    t0 = time.time()

    # 2. new take of the selection, conditioned on everything before it. A take that repeats the
    #    original (many identical tokens) is re-rolled with another seed so every take is a new version.
    for attempt in range(MAX_REROLLS + 1):
        leg = _semantic(_run(lyrics, seed, {**options, "semantic_prefix": json.dumps(tokens[:a]),
                                            "semantic_min_tokens": str(b), "semantic_max_tokens": str(b),
                                            "stop_after": "semantic"}))
        same = sum(x == y for x, y in zip(leg[a:b], tokens[a:b])) / (b - a)
        if same <= MAX_SAME_TOKENS:
            break
        seed = (seed + 7919) % 2**63
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
            "seed": seed, "same_tokens": round(same, 3), "variation": variation, "elapsed_s": round(time.time() - t0, 1)}
    return out, info


def beat_grid(song: str) -> dict:
    """Tempo and downbeat of a song, so edits can snap to beats and bars (cached in the song's json).

    Onset strength (spectral flux) autocorrelation picks the beat period; the score's Q:/M: header,
    when the song was planned, narrows the tempo search and gives the bar length.
    """
    meta_path = engine.OUTPUT_DIR / f"{song}.json"
    meta = json.loads(meta_path.read_text())
    if "beats" in meta:
        return meta["beats"]

    prior_bpm, per_bar = None, 4
    score = meta.get("artifacts", {}).get("score")
    if score and (engine.OUTPUT_DIR / score).exists():
        abc = (engine.OUTPUT_DIR / score).read_text()
        import re
        if m := re.search(r"^Q:\s*(\d+)/(\d+)\s*=\s*(\d+)", abc, re.M):
            prior_bpm = float(m.group(3)) * 4 * int(m.group(1)) / int(m.group(2))   # in quarter notes
        if m := re.search(r"^M:\s*(\d+)/(\d+)", abc, re.M):
            per_bar = int(m.group(1))

    x = _pcm((engine.OUTPUT_DIR / f"{song}.wav").read_bytes()).mean(axis=1)
    hop, n_fft = 512, 2048
    frames = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    mag = np.log1p(np.abs(np.fft.rfft(x[idx] * np.hanning(n_fft), axis=1)))
    onset = np.maximum(0, np.diff(mag, axis=0)).sum(axis=1)
    onset = (onset - onset.mean()) / (onset.std() + 1e-9)
    fps = SR / hop

    # comb scan: for every candidate tempo, how strongly do onsets line up on a beat grid at its best phase
    # YuE2 renders a planned song from its score, so the score tempo is trusted (±1.5% for drift);
    # without a score the whole 70-180 BPM range is scanned.
    lo_bpm, hi_bpm = (prior_bpm * 0.985, prior_bpm * 1.015) if prior_bpm else (70.0, 180.0)

    def alignment(p: float) -> tuple[float, float]:
        phases = np.arange(0, p, 0.5)
        means = [onset[np.arange(ph, len(onset) - 1, p).astype(int)].mean() for ph in phases]
        k = int(np.argmax(means))
        return means[k], float(phases[k])

    candidates = []
    for bpm in np.arange(lo_bpm, hi_bpm + 1e-6, 0.1 if prior_bpm else 0.25):
        score_b, ph = alignment(fps * 60 / bpm)
        # without a score, a mild preference for 90-140 BPM settles half/double-tempo ties
        prior = 1.0 if prior_bpm else np.exp(-0.5 * (np.log2(bpm / 115.0) / 0.8) ** 2)
        candidates.append((score_b * (0.85 + 0.15 * prior), bpm, ph))
    _, bpm_best, phase = max(candidates)
    period = fps * 60 / bpm_best
    beat_strength = [onset[(np.arange(phase + k * period, len(onset) - 1, period * per_bar)).astype(int)].sum()
                     for k in range(per_bar)]
    downbeat = phase + int(np.argmax(beat_strength)) * period

    beats = {"bpm": round(float(60 * fps / period), 2), "offset_s": round(float(downbeat / fps % (period * per_bar / fps)), 3),
             "beat_s": round(float(period / fps), 4), "beats_per_bar": per_bar, "source": "score+audio" if prior_bpm else "audio"}
    meta["beats"] = beats
    meta_path.write_text(json.dumps(meta, indent=2))
    return beats
