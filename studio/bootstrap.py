"""Read native build targets from the catalog; bootstrap never chooses a model."""

import argparse
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def families():
    catalog = json.loads((ROOT / "config/model-catalog.json").read_text())["models"]
    names = sorted({m["family"] for m in catalog if m["provider"] == "audio.cpp" and m.get("delivery", "local") == "local"})
    if not names or any(not re.fullmatch(r"[a-z0-9_]+", name) for name in names):
        raise ValueError("The catalog must declare valid native model families")
    return names


def compatible(cache_path):
    if not cache_path.is_file(): return False
    values = dict(line.split("=", 1) for line in cache_path.read_text().splitlines() if "=" in line and not line.startswith(("#", "//")))
    compiled = re.split(r"[,;]", values.get("AUDIOCPP_MODELS:STRING", ""))
    return values.get("AUDIOCPP_MODEL_SET:STRING") == "full" or set(families()).issubset(compiled)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["families", "compatible"])
    parser.add_argument("cache", nargs="?", type=Path)
    args = parser.parse_args()
    if args.command == "families": print(",".join(families()))
    else: raise SystemExit(0 if args.cache and compatible(args.cache) else 1)


if __name__ == "__main__": main()
