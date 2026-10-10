# Project handoff

## Current task

Branch: `feat/model-settings-harness`.
Scope: product naming cleanup (#4) and a contributor harness independent of the
coding CLI. Architecture and acceptance scenarios preserve the agreed work for
#2 (providers/startup), #3 (Settings/downloads), and #1 (song endings).

## Verified context

- The current app uses audio.cpp with YuE2-3B Q8_0 and an F16 VAE.
- Startup currently requires the engine; setup downloads fixed model weights.
- Settings, user-requested model downloads, and provider extraction are pending.
- A saved 180-second song reached 4,500 semantic frames. The previous engine log
  reported semantic truncation while the score planner completed. See #1 for the
  analysis; increasing precision is not an established ending fix.
- Published YuE2 main BF16 and VAE F32 files exist. Main BF16 must not be called
  FP16. Main and VAE precision are separate profile choices.

## Changes in this branch

Product/package naming now uses Lux In Music / `lux-in-music`. The dependency
versions are preserved. An offline lock resolution initially lacked compatible
cached packages; after updating the editable package identity, the lock consistency
check succeeded without changing dependency versions.

Added canonical instructions, small CLI bridges, architecture, requirement ledger,
portable checks, an offline regression suite, and a GitHub Actions baseline gate.

## Verification

- `python3 scripts/check.py`: passed, including five harness regression tests.
- `.venv/bin/python scripts/check.py --full`: passed, with 12 tests total.
  API/browser product names, metadata, CLI help, offline engine health, and
  current request boundaries were checked without real inference.
- `.venv/bin/python scripts/check.py --require-complete`: exited 1 as intended.
  Application tests passed; the sole failure was the remaining planned product
  requirements. The JSON report was checked to confirm this distinction.
- `uv lock --check --offline` with a temporary cache: passed (21 packages).
- `git diff --check`: passed; project-owned files have no retired brand matches.

The workflow is configured but has not run on GitHub yet. No live audio generation
or graphical browser session was needed for this naming/harness change. The
Settings/download flow remains planned in #2/#3; this branch records its required
behavior rather than claiming those features already work.

## Next delivery

Extract the current audio.cpp/YuE2 boundary (#2), then build Settings and downloads
(#3), with model/component licenses visible before download. Start with the
empty-install UI flow, use fake providers in tests, and retain the existing library.
