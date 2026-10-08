"""Generate one song to a WAV file from the command line.

    uv run studio-gen --lyrics-file song.txt --style "English, indie pop, ..." --seed 42
"""

import argparse
import sys
from pathlib import Path

from . import engine
from .params import GenerationParams


def main() -> None:
    ap = argparse.ArgumentParser(description="YuE2 text-to-music -> WAV")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--lyrics", help="lyrics text (use \\n for new lines)")
    src.add_argument("--lyrics-file", type=Path)
    ap.add_argument("--style", required=True)
    ap.add_argument("--cot", choices=["off", "melody", "full"], default="off")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--steps", type=int, dest="num_inference_steps")
    ap.add_argument("--guidance", type=float, dest="guidance_scale")
    ap.add_argument("--max-duration", type=float, dest="max_duration_s", help="max length in seconds")
    ap.add_argument("--abc-file", type=Path)
    ap.add_argument("--name", help="output file stem (default: timestamp-seed)")
    a = ap.parse_args()

    lyrics = a.lyrics_file.read_text() if a.lyrics_file else a.lyrics.replace("\\n", "\n")
    params = GenerationParams(
        lyrics=lyrics, style=a.style, cot=a.cot, seed=a.seed,
        num_inference_steps=a.num_inference_steps, guidance_scale=a.guidance_scale,
        max_duration_s=a.max_duration_s,
        abc=a.abc_file.read_text() if a.abc_file else None,
    )
    try:
        engine.health()
    except Exception as e:
        sys.exit(f"audio.cpp server not reachable at {engine.ENGINE_URL} ({e}). Run scripts/run_engine.sh")

    print(f"Generating (cot={params.cot}, seed={params.seed}) ...", flush=True)
    res = engine.generate(params, a.name)
    print(f"Saved {res.wav_path}  ({res.duration_s:.1f}s audio in {res.elapsed_s:.0f}s, "
          f"{res.sample_rate} Hz x{res.channels})")
    for k, p in res.artifacts.items():
        print(f"  {k}: {p}")


if __name__ == "__main__":
    main()
