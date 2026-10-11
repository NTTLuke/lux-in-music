# Project handoff

## Current work: stop a generation

- `POST /api/jobs/{id}/cancel` removes a queued job of any kind, or stops a
  running generation. Job cards show a stop button; cancelled jobs leave the list.
- audio.cpp has no request cancellation, so `AudioCppProvider.cancel` terminates
  the generation engine. The worker marks the job `cancelled`, not `error`, and
  no song or failure report is written. Steps of a multi-step YuE2 generation
  check the stop request before each engine call, also after an engine restart.
- Verification: offline API test with a blocking fake provider (queued and
  running jobs, no output written), a provider test for a stop during engine
  start, and a browser check for the stop button. Full checks pass. A real
  audio.cpp generation was stopped in `./studio.sh` on macOS (Metal) 5 s after
  it started; it ended `cancelled` with no output, and the next generation
  restarted the engine and finished a song (about 3 minutes).
- Limits: the next job pays the model load again. Running separation and stem edits cannot be stopped yet;
  they run several engine calls that do not check the stop request.
- Next step: allow stopping running separations and stem edits.

## Current work: manual release build

Branch: `feat/manual-release-build`, based on main after PR #9.

- Added `release.sh` (entry point) and `scripts/release.py` (all steps): preflight,
  repository checks, version bump, `CHANGELOG.md` entry, README release block,
  release commit and tag, artifacts, push, GitHub release and asset verification.
- Versioning comes from `pyproject.toml`. `./release.sh patch|minor|major` bumps
  it; an explicit version such as `0.2.0` sets it; the current version can be
  released as-is while it has no tag yet, which is how the first release is made.
- Release notes are generated offline with `git log --first-parent`: merged pull
  requests use their PR title and their branch prefix (`feat/`, `fix/`, `docs/`,
  `test/`, `chore/`) for the section, and commits made directly on `main` are
  categorized from their subject. No API call is needed to build the notes.
- Artifacts are built from the tag itself: a source ZIP with the
  `lux-in-music-<version>/` prefix (the folder the installation guide asks for),
  the wheel, the sdist and `SHA256SUMS.txt`. The script then reads the published
  release back and fails if an asset is missing or empty.
- README gained "Releases and changelog" with the latest version and download
  links, refreshed between `<!-- release:start -->` / `<!-- release:end -->`
  markers; step 2 of the installation guide now downloads the release ZIP instead
  of the moving source. `CHANGELOG.md` was added. AGENTS.md and CONTRIBUTING.md
  document the command and the release-note conventions.
- The script refuses to run on a dirty tree, away from `main`, when `main` is not
  in sync with `origin/main`, when the tag exists, when `dist/` is not ignored, or
  when Git has no `user.name`/`user.email`. `--dry-run` prints everything and
  writes nothing, `--no-push` stops after the local build.
- Verification: `python3 scripts/check.py` passes with the new files. The whole
  flow was exercised end to end on a clone with a local bare remote (first
  release at the current version, then a patch release): correct range from the
  previous tag, correct `CHANGELOG.md` ordering, no duplicate sections when a step
  is re-run, README markers replaced rather than duplicated, executable `studio.sh`
  in the ZIP, and matching checksums. Error paths were exercised for a dirty tree,
  another branch, an existing tag and an older requested version.
- Limits: the run itself was tested on Linux; macOS uses the same `git`, `uv` and
  `gh` commands, and the ZIP extracts with `studio.sh` marked executable in the
  archive. `gh release create` and the asset read-back run for the first time on
  the first real release, which is v0.1.0.
- Next step: publish v0.1.0 from `main` and confirm the four downloadable assets,
  then use `./release.sh patch` for follow-up fixes.

## Delivered: simple local installation guide

Branch: `docs/simple-local-installation`, based on main after PR #8.

- Reorganized README around five beginner steps for Apple Silicon: prepare
  Apple's tools, download/extract the GitHub ZIP, enter the folder using Finder
  drag-and-drop, run `./studio.sh`, choose a model in Settings and create the
  first example. Explain startup stages, model downloads, license review,
  reopening, Control + C, file locations and common recovery commands.
- The example starts with the Melodic Techno demo and its four-minute target;
  the genre templates reuse those lyrics. Technical architecture, launch
  options, Linux CPU limitations and contributor commands follow the user guide.
- Checked commands and button names against `studio.sh`, `scripts/setup.sh`,
  `studio/launch.py`, the Finder launcher and Settings UI. Installation behavior
  and model defaults are unchanged. No real setup/download/generation is needed
  for this documentation update.
- Verification passed: portable baseline (five harness tests), five offline
  bootstrap tests, launcher `--help` confirming port/browser flags, and
  `git diff --check`. No fresh real native build is claimed for this doc change.
- The user also requested a playable README preview and explicitly authorized
  uploading only the accepted Complete Demo. Uploaded one 6.49 MB H.264/AAC
  MP4 attachment with a static cover and the full song (about 237.5 seconds,
  48 kHz stereo). Source WAV remains in the local Library; no model files,
  other songs, settings or runtime artifacts were uploaded. The media file is
  an attachment, outside Git history and installation ZIPs.
- Preview attachment: https://github.com/user-attachments/assets/51a82812-f433-4d41-804c-e34d2c7c23a7
  Native GitHub video rendering uses the standalone attachment URL in README.
  Repository access is required while this repository is private.
- GitHub's Markdown renderer returned a native video element with controls.
  Chrome loaded the uploaded 1280×720 media, reported a 237.5-second duration,
  played it and reached the end after seeking to the final seconds, with no
  media error. GitHub starts it muted, so README explicitly says to enable sound.
  This is remote playback verification; human listening acceptance belongs to
  the original full-song test recorded below. No signed media URLs are committed.

## Delivered: Create layout and genre templates

Branch: `feat/create-layout-genre-templates`, based on main after PR #7.
PR #8 is merged into main (`4f744840ed76f804235f4fdc444845914d5af3b7`), with
passing CI, after the user accepted the templates and shared lyric text.

- Create is 520 px wide on large desktop screens (previously 440 px), with
  the remaining width assigned to Library. Medium screens use a bounded
  proportional width; the mobile view stays stacked. Hide library mini-waves
  below 1320 px to keep song titles and actions usable.
- An expandable Genre templates section beneath the existing Melodic Techno
  demo offers five styles: Progressive Metal, Indie Pop, Cinematic Synthwave,
  Soul & R&B, and Jazz Fusion. Following the user's correction, every template
  loads the same lyric text as the Melodic Techno demo with its genre style,
  preserving title, duration, seed and planning. It sends no generation
  request. Selection is highlighted and cleared when the style is edited.
- Portable baseline and full offline harness passed (67 tests). The extended
  isolated Chrome flow passed with no JavaScript errors: all five presets apply,
  load the exact demo lyrics, preserve title/settings and cause no generation requests; the demo remains in
  Create. Layout checked at 1440/1280/1024/900/390 px without horizontal overflow.
  Desktop and mobile screenshots were inspected under `/private/tmp/lux-templates-ui/`.
- No real audio generation was run for this change. These are style starting
  points, not claims of measured musical quality for each genre.

## Delivered: duration-aware song endings (#1)

Branch: `fix/duration-aware-song-endings`, based on merged PR #6.
The technical flow is implemented and verified. The user accepted the linked
test audio on 2026-10-10 with "è perfetta !! bravo". This records human listening
acceptance for that example; the ledger is implemented. PR #7 was merged into
main (`664183745a11ba9b665ad99cb966799c8495d92d`) and issue #1 is closed.
See [song endings](song-endings.md) for the upstream analysis and exact policy.

- Root cause confirmed in three saved songs: plans of 318.72/336.39/286.45 seconds
  were stopped at semantic caps of 180/180/120 seconds. No composition time budget
  reached the old planner. An outro lyric tag alone did not fix that mismatch.
- Complete arrangement now uses a separate target, score-only inspection,
  conservative instrumental shortening, native groups of up to four measures,
  bounded planning and semantic retries, and EOS/duration checks before rendering.
  Vocal bars, breathing rests, tempo and ending bars are retained. Supplied scores
  stay intact. Clip mode retains the hard cap and explicitly labels truncation.
- The UI has target/cap modes, lyric word/ending advice, named job stages and
  ending badges/details. Existing verified profiles receive these capabilities
  without a new probe/download. Original and adapted plans, token attempts,
  composing-stage EOS and forced-render metadata are stored separately. Token
  recovery uses the actual adapted score and recorded semantic retry seed.
- `.venv/bin/python scripts/check.py --full`: passed, 67 tests (five harness and
  62 application tests). Sixteen new checks cover duration, integrity, stages,
  retry bounds, storage, legacy profiles and semantic recovery. Planned-work
  checks now run in the full harness without changing their acceptance status.
- Isolated Chrome flow passed: target/cap controls, Full score selection,
  dense-text/outro guidance, submitted target without cap, unfinished badges,
  plus the previous Settings, library and mixer flows. No JavaScript errors.
  Final screenshot was inspected at `/private/tmp/lux-ending-ui-final/duration-desktop.png`.
- Real Metal semantic trials with existing Q8_0/F16 weights and a 240-second
  adapted score emitted EOS at 237.52 and 237.92 seconds, seeds 454234436/437.
  The earlier one-bar rewrite hit 270 seconds; keeping native groups succeeded.
  Textual duration instructions alone produced overlong/malformed exploratory
  plans, so the implementation checks actual notation instead of relying on them.
- **Full application generation passed:** target 240 seconds, hard limit 270,
  seed 454234436, generated plan 318.72 seconds at 125 BPM, adapted plan 240 seconds
  (41 instrumental bars removed), one successful semantic attempt, EOS after
  5,938 frames, actual WAV 237.5187 seconds, 48 kHz stereo, total wall time 264 s.
  Profile `yue2-3b--q8_0--f16`, weights release `cca74d8980c00f30ab8d52248a367c01ad633ec2`,
  audio.cpp revision `6c3ab9ad4e599a44d287697863b4f8846ef658be`. No new weights or
  active Settings changes. The test runtime was closed after the run.
- Durable local evidence: `outputs/checks/endings/20261010-target-240/` contains
  `target-240.wav`, metadata, source/adapted scores and semantic tokens. WAV SHA-256:
  `089918fc008347c1fbad47ede6260c797588ad8daf9c47f780a905a8308a8446`.
  The last seconds decay from roughly -14 to -61 dBFS; this signal measurement
  supports a quiet tail but does not prove a satisfactory musical ending.
- **Listening acceptance:** after receiving the WAV link, the user reported
  "è perfetta !! bravo" on 2026-10-10. This is user acceptance, not an automated
  listening analysis or a line-by-line lyric audit. The local test record now
  includes that review. New generations still start with `listening_verified=false`.
  PR #7 is merged and #1 is closed. Other styles,
  languages, seeds and BF16/F32 are not covered by this single audio example;
  failures are bounded and explained, not hidden.

The sections below describe the earlier delivered PR #5/#6 work and its evidence.

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
