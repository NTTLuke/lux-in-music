"""Shared PCM/WAV, crossfade, and beat-grid utilities independent of model codecs."""

import io
import json
import wave
import numpy as np
from . import engine

XFADE_S = 0.2

def pcm(wav_bytes: bytes) -> np.ndarray:
    with wave.open(io.BytesIO(wav_bytes)) as w:
        x = np.frombuffer(w.readframes(w.getnframes()), "<i2").reshape(-1, w.getnchannels())
    return x.astype(np.float32) / 32768.0


def wave_bytes(x: np.ndarray, sample_rate: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(x.shape[1]); w.setsampwidth(2); w.setframerate(sample_rate)
        w.writeframes((np.clip(x, -1, 1) * 32767).astype("<i2").tobytes())
    return buf.getvalue()


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

    x = pcm((engine.OUTPUT_DIR / f"{song}.wav").read_bytes()).mean(axis=1)
    hop, n_fft = 512, 2048
    frames = 1 + (len(x) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(frames)[:, None]
    mag = np.log1p(np.abs(np.fft.rfft(x[idx] * np.hanning(n_fft), axis=1)))
    onset = np.maximum(0, np.diff(mag, axis=0)).sum(axis=1)
    onset = (onset - onset.mean()) / (onset.std() + 1e-9)
    with wave.open(str(engine.OUTPUT_DIR / f"{song}.wav")) as audio:
        sample_rate = audio.getframerate()
    fps = sample_rate / hop

    # comb scan: for every candidate tempo, how strongly do onsets line up on a beat grid at its best phase
    # A score-conditioned song follows its score tempo, so the score tempo is trusted (±1.5% for drift);
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
