"""Generate one song to a WAV file from the command line.

    uv run studio-gen --lyrics-file song.txt --style "English, indie pop, ..." --seed 42
"""

import argparse
import json
import sys
from pathlib import Path

from . import engine
from .params import GenerationParams


def main() -> None:
    ap = argparse.ArgumentParser(description="Lux In Music: generate with the model selected in Settings")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("--lyrics", help="lyrics text (use \\n for new lines)")
    src.add_argument("--lyrics-file", type=Path)
    ap.add_argument("--style", required=True)
    ap.add_argument("--cot", choices=["off", "melody", "full"], help="YuE2 planning option")
    ap.add_argument("--seed", type=int, default=1234)
    ap.add_argument("--steps", type=int, dest="num_inference_steps")
    ap.add_argument("--guidance", type=float, dest="guidance_scale")
    ap.add_argument("--max-duration", type=float, dest="max_duration_s", help="max length in seconds")
    ap.add_argument("--target-duration", type=float, dest="target_duration_s", help="complete arrangement target in seconds; supported models plan before rendering")
    ap.add_argument("--abc-file", type=Path)
    ap.add_argument("--model-options", type=json.loads, default={}, help="JSON object with options for the selected model")
    ap.add_argument("--name", help="output file stem (default: timestamp-seed)")
    a = ap.parse_args()

    lyrics = a.lyrics_file.read_text() if a.lyrics_file else a.lyrics.replace("\\n", "\n")
    if not isinstance(a.model_options, dict):
        ap.error("--model-options must be a JSON object")
    options = dict(a.model_options)
    for key, value in {"cot": a.cot, "num_inference_steps": a.num_inference_steps,
                       "guidance_scale": a.guidance_scale,
                       "abc": a.abc_file.read_text() if a.abc_file else None}.items():
        if value is not None:
            if key in options and options[key] != value:
                ap.error(f"Conflicting model option: {key}")
            options[key] = value
    params = GenerationParams(lyrics=lyrics, style=a.style, seed=a.seed,
                              max_duration_s=a.max_duration_s, target_duration_s=a.target_duration_s, model_options=options)
    try:
        if engine.health().get("setup_required"):
            sys.exit("Choose and activate a model first: run ./studio.sh and open Settings.")
    except Exception as e:
        sys.exit(f"Model setup unavailable ({e}). Run ./studio.sh and open Settings.")

    print(f"Generating (seed={params.seed}) ...", flush=True)
    res = engine.generate(params, a.name)
    print(f"Saved {res.wav_path}  ({res.duration_s:.1f}s audio in {res.elapsed_s:.0f}s, "
          f"{res.sample_rate} Hz x{res.channels})")
    for k, p in res.artifacts.items():
        print(f"  {k}: {p}")


if __name__ == "__main__":
    main()
