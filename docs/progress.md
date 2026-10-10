# Project handoff

## Delivered scope

Implementation branches: `feat/model-settings-harness` and
`feat/model-manager-bootstrap`.
Scope: #2 provider/model independence and #3 Settings, licenses, downloads and
precision choices. The user also requested first-run software installation from
`studio.sh`, with visible progress and no automatic model downloads.

The naming cleanup and portable contributor harness are delivered through PR #5;
model setup, provider boundaries and their follow-up fixes are delivered through
PR #6. Natural song endings (#1) remain a separate task.

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

- `.venv/bin/python scripts/check.py --full`: passed, 51 tests total (five harness
  regressions and 46 application tests). Only natural-song-ending remains planned.
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
  remain separate. Push and PR checks passed for the final implementation revision.

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

## Separation activation format follow-up

The user's screenshot showed successful YuE2 Q8_0/F16 and SAM Audio activation,
but HTDemucs 4/6 stems and BS-RoFormer failed with an input-rate mismatch:
expected 44,100 Hz, received 48,000 Hz. The native probe generated the same 48 kHz
test input for every separator. The application separation path already used
different rates, so the probe did not exercise the same input contract.

The catalog now declares each separator's input rate/channels and copies them
into its profile. Probes and normal separation use this declaration; older
profiles keep the mode-format fallback. Real native testing exposed a second
probe error after fixing the rate: HTDemucs rejects the generic `seed` option.
The probe now sends only audio to HTDemucs/BS-RoFormer, and text/seed to SAM Audio.
Setup error hints allow retrying verification rather than always suggesting
another download.

- Offline regression checks inspect the actual WAV sent by each native probe,
  permitted request keys, missing input contracts, and a fake separator requiring
  a different rate from the mode default. Full harness: 45 tests passed.
- Real Metal probes with existing Q8_0 files passed for HTDemucs 4 stems,
  HTDemucs 6 stems and BS-RoFormer, each returning nonempty WAV audio at the
  corrected input contract. Results were saved in
  `/private/tmp/lux-separation-probe-results.json`.
- No model weights were downloaded or active Settings changed by these tests.
  Each test runtime was closed afterwards. This is runtime compatibility evidence,
  not a listening test or proof of separation quality on real songs.
- Updated the user's current temporary archive after checking the affected source
  files matched the committed version. The running app needs a restart before
  retrying Verify existing files for those three models. Successful profiles and
  recorded license reviews remain in its settings file.

## Settings persistence and licensing follow-up

The user reported that verification appeared to reset on launch and dropdown
changes. Their stored profiles and fingerprints were still valid: YuE2 and SAM
remained ready. The browser reset to catalog defaults, forgot license checkbox
state, and still offered verification for already verified active profiles.

Settings now restores the active combination and accepted review IDs, retains
acceptance when a dropdown changes within the same license release, and labels
active profiles as Verified. Selecting another verified profile reuses its saved
validation. New files/releases and changed runtime tokens still require checks;
repair explicitly rechecks. Four new offline cases cover restart/reselection,
changed release/runtime/files and explicit repair. Full harness: 49 tests passed.
The isolated browser flow also passed reload/dropdown persistence without
JavaScript errors. The user's temporary app sources were updated; restart is
required to load the new backend.

The requested online license double-check found an additional individual creator
permission in the original GitHub README and MODEL_LICENSE. Personal creators can
monetize outputs; companies need a commercial weight license. The base weight
license remains CC BY-NC 4.0. Links and scope are recorded in
`docs/model-licenses.md`; the pinned GGUF identifier was not relabeled as Apache.

## Model cards and mixer follow-up

The user requested implicit verification in the setup button and no accumulated
setup log above Settings. Each card now owns a single setup action and its progress
or latest relevant error. Active verified separators use the same disabled
Active / Verified state as the generation model. Completed attempts are hidden;
repair is available under Maintenance. An unselected verified combination still
offers activation, and an unverified combination still needs setup.

The YuE2 card now displays the additional individual creator permission and its
immutable GitHub source revision alongside the base weight licenses. Revised
license details require one new acknowledgement; already validated weights/runtime
do not need another probe for that acknowledgement. Two new offline tests cover
the pinned terms and this review/validation distinction. Full harness: 51 tests.

The user's Studio Mode stack trace exposed `set` being used outside its scope in
`trackRow`. It was reached only for songs with editing enabled, which explains
why another song could still open. The renderer now passes the stem set explicitly.
The browser regression opens both a legacy noneditable song and an editable song,
renders two tracks, and opens the edit bar. No JavaScript errors occurred.

The full isolated browser flow also passed active-separator buttons, card progress,
local error/retry handling, hidden maintenance actions and visible creator terms.
Desktop/mobile screenshots were captured; the desktop result was inspected.
The current temporary archive is updated after source comparisons. A restart
loads the changed catalog/backend; a browser reload loads the new UI scripts.
