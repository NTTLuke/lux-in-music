# Repository instructions

## Purpose and scope

Lux In Music is generative music software. Its first local runtime is audio.cpp.
The product must support different compatible models through adapters, with
model setup owned by Settings. Read [docs/architecture.md](docs/architecture.md)
before changing startup, model selection, download, or generation behavior.

These instructions apply to humans and coding agents using any CLI. This is the
canonical instruction file. Tool-specific entry files only point here. If your
tool does not load it automatically, read it explicitly before working.

## Start a task

1. Read `git status --short --branch` and preserve existing user changes.
2. Read the relevant issue, `docs/progress.md`, and `harness/requirements.json`.
3. Choose a focused change on a task branch. Keep unrelated issues separate.
4. Check actual files and upstream documentation before relying on assumptions.

## Commands

- Portable baseline: `python3 scripts/check.py` (Python 3.11+, Node.js, Bash).
- Application checks: `.venv/bin/python scripts/check.py --full` after dependency setup.
- Browser flow: `uv run --no-project --with playwright python scripts/check_ui.py`
  with an installed Chrome, or `LUX_TEST_BROWSER` set to its executable.
- Dependency setup: `uv sync --frozen` uses the committed lock file.
- Lock consistency: `uv lock --check --offline` with an accessible uv cache.
- Current app launcher: `./studio.sh`; individual UI: `scripts/run_studio.sh`.
- Current generation CLI: `uv run studio-gen --help`.

The automated checks never download models, call a real inference engine, or require a GPU.
Actual audio changes also need a recorded audio test and listening check.
`scripts/setup.sh` prepares software only. `studio.sh` runs it before launching
the UI. Use dependency setup alone when doing code-only work.

## Architecture rules

- Keep shared song inputs, job queue, library, and UI separate from model adapters.
- audio.cpp-specific transport belongs at the runtime boundary; model-specific
  token rates, planning, and sampling belong to the relevant model adapter.
- Future providers must declare capabilities; show only supported controls.
- Separate generation model setup from optional separation model setup.
- A fresh install opens Settings without downloaded weights or a running
  inference engine. Keep this behavior covered by bootstrap and API tests.
- Downloads require model and component license details shown beforehand and
  an explicit user action. Do not add silent downloads to install or startup.
- Use exact artifact precision names. BF16 and FP16 are different formats.
  YuE2 main Q8_0/BF16 and VAE F16/F32 are independent choices. VAE F16 is the
  default after selecting YuE2, not a reason to download it automatically.
- Record the effective model profile with each job/song. Settings changes must
  not alter running/queued jobs or silently reconfigure old songs for editing.
- Treat a duration cap as a cap. A playable WAV or successful engine request
  does not prove a complete song; retain truncation and ending information.

See the architecture document for current limitations and the target design.

## Contribution and verification

- Use Lux In Music for product names and `lux-in-music` for package identifiers.
- Keep code, project documentation, issues, and PRs in simple English.
- Issues and PRs need the problem, relevant analysis, proposed/resulting behavior,
  and verification. Separate observed evidence from hypotheses.
- Use existing Python/FastAPI and plain JavaScript conventions. Add abstractions
  for a concrete model boundary, rather than speculative frameworks.
- Keep downloaded models, generated songs, secrets, and runtime logs out of Git.
- For behavior changes, add tests at the changed boundary using temporary files
  and fake providers/transports. Keep core checks independent of GPU/network.
- Run the baseline and the relevant application checks. Do not weaken checks or
  mark requirements implemented to hide a failing or untested behavior.
- Update `docs/progress.md` with results, limitations, and the next concrete step.
  Add new product decisions to `docs/architecture.md`; update the requirement
  ledger when the corresponding behavior has executable verification.
- A green baseline is not proof that planned product requirements work. Keep
  their status accurate and preserve the issue links.

## Code map

- `studio/app.py`: API, queue, library, static app serving.
- `studio/engine.py`, `studio/params.py`: shared generation inputs and artifacts.
- `studio/providers.py`: runtime registry, lifecycle, transport, compatibility probes.
- `studio/adapters/`: model request validation, capabilities, token formats, editing.
- `studio/models.py`, `config/model-catalog.json`: profiles, licenses, pinned downloads.
- `studio/edit.py`, `studio/separate.py`, `studio/audio.py`: editing facade, separation, audio helpers.
- `studio/bootstrap.py`, `studio/launch.py`: software build targets and UI-first launch.
- `studio/static/`: browser UI, player, and multitrack studio.
- `config/`, `scripts/`, `studio.sh`: current runtime setup and launch.
- `harness/`, `tests/`, `scripts/check.py`: shared requirements and checks.
