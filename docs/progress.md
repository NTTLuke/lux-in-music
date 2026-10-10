# Project handoff

## Current task

Branch: `feat/model-manager-bootstrap`, based on `feat/model-settings-harness`.
Scope: #2 provider/model independence and #3 Settings, licenses, downloads and
precision choices. The user also requested first-run software installation from
`studio.sh`, with visible progress and no automatic model downloads.

The naming cleanup and portable contributor harness are in draft PR #5. This
branch builds on that work. Natural song endings (#1) remain a separate task.

## Changes

- `studio.sh` runs software-only setup, prepares Python 3.12/locked dependencies,
  installs missing uv locally, and builds the pinned native families when needed.
  Terminal stages and compiler output report progress. Warm startup skips a
  compatible build. Missing Apple compiler tools give an actionable instruction.
- The UI starts with no model or engine and opens Settings first. Library audio
  remains accessible. No active model is chosen or downloaded automatically.
- Shared inputs/results/queue use provider contracts. YuE2 options, semantic
  token rates and editing live in model adapters. Capability declarations control
  which UI inputs are offered. A fake external provider also works without
  local weights, precision or a VAE; no actual MiniMax integration was added.
- Settings offers generation and optional separation models independently.
  Main Q8_0/BF16/Q4_0 and VAE F16/F32 are independent; BF16 is not called FP16.
- The catalog pins release URLs, file sizes, hashes and component license sources.
  Licenses are displayed and acknowledged before transfer. Unknown licenses block
  setup. BS-RoFormer retains the publisher's checkpoint-provenance caveat.
- Downloads show progress, verify files, resume supported ranges, and support
  cancellation/retry. Existing legacy files are verified and reused. Profiles
  are activated only after a short runtime test and persistent settings save;
  failures preserve the last working selection, including failed disk writes.
- Queued jobs, saved songs and stem sets retain their effective profile. Editing
  resolves original profiles; missing/incompatible files require verification.
  Device/backend or binary changes require another test before activation.
- The requirement ledger and CI now cover #2/#3 and software bootstrap. The full
  harness deduplicates shared test selectors while reporting each requirement.

## Verification

- `.venv/bin/python scripts/check.py --full`: passed, 42 tests total (five harness
  regressions and 37 application tests). Only natural-song-ending remains planned.
- Lock consistency check passed offline (21 packages); `git diff --check` passed.
- Fresh Python environment: real `uv sync --frozen --python 3.12` succeeded in
  `/private/tmp/lux-fresh-environment` using the existing lock file.
- Actual warm `NO_OPEN=1 ./studio.sh --port 18000` prepared dependencies, reused
  the existing native build, and served the UI with no active model/engine.
- Cold software bootstrap, local uv installation, warm reuse, and prerequisite
  failure are checked with fake local tools. After the SSH failure follow-up,
  an actual clean native build succeeded in the user's fresh archived copy on
  this Mac. A build on another machine has not been verified.
- Real Metal runtime probe using the already downloaded YuE2 Q8_0/F16 files
  succeeded and returned nonempty audio. No new real model weights were fetched.
  The probe is a compatibility check, not a listening or song-ending test.
- Published hashes and sizes matched all existing Q8_0/F16 YuE2 files and sidecars.
- Read-only browser check of the real catalog: five model cards, F16 VAE default,
  license gating, BF16/F32 selection (~7.79 GB files), library access and mobile
  navigation. No download/activation request was sent for real models.
- Isolated Playwright/Chrome flow passed: Settings first, licenses, BF16/F32,
  fake download/probe/activation, conditional controls, generated library entry,
  mobile navigation, an external profile without weights, unresolved-license
  controls blocked. No JavaScript errors. Screenshots were inspected.

## Limits and next steps

- BF16/F32 and optional separators are not claimed as tested on every device.
  Their actual activation performs the runtime test on the user's computer.
- #1 remains open. YuE2's maximum duration still sets a semantic token cap; it
  does not guide a full composition to a natural ending. Existing evidence:
  a 180-second request reached 4,500 frames and reported semantic truncation while
  score planning completed. Increasing precision is not an established fix.
- Preserve truncation metadata and add composition-ending evidence/listening
  checks when implementing #1. Do not mark it implemented based on a valid WAV.
- Additional providers need concrete adapters, catalog entries and capability
  tests. External service authentication and billing have not been implemented.
- CI runs portable and offline application checks. Native GPU and browser checks
  remain separate; verify the remote CI result after publishing this branch.

## First-run SSH failure follow-up

The user tested a fresh source archive while reusing existing model files.
The pinned audio.cpp `.gitmodules` declares `audio.cpp-server-frontends` using
`git@github.com`, so recursive source setup failed without a GitHub SSH key.
The previous fake-installer tests did not reproduce that transport requirement.

Setup now passes GitHub SSH-to-HTTPS rewrites only to the submodule command and
its child processes. This handles both SSH URL forms and already registered URLs
left by a failed `--init`, without changing the global Git configuration.
See [Git's URL rewrite documentation](https://git-scm.com/docs/git-config#Documentation/git-config.txt-urlltbasegtinsteadOf).

A new offline regression runs the setup against a real local Git submodule index
with HTTPS and SSH transports blocked. Both URL forms reach the HTTPS restriction
rather than SSH, and the fixture's global config remains unchanged. The full
harness passes (42 tests). The user's existing temporary checkout successfully
fetched the pinned frontend commit over HTTPS, compiled both native CLI/server
targets from scratch, and started the UI on port 18001. The Settings API reported
`setup_required: true`, with no active model. The test server was stopped after
verification. No model weights were downloaded or selected. The corrected setup
script was also copied into that temporary archive so the user can resume there.
