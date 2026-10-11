# Contributing to Lux In Music

Read [AGENTS.md](AGENTS.md) for repository rules and commands, then
[docs/architecture.md](docs/architecture.md) for the agreed product direction.
The same workflow applies to people and to any coding CLI.

## Prepare

Use Python 3.11 or later, Node.js, Bash, and Git. The application uses Python
dependencies managed by uv. Start on a dedicated branch and inspect existing
changes before editing.

```bash
uv sync --frozen
python3 scripts/check.py
.venv/bin/python scripts/check.py --full
```

Only the dependency setup command needs a package cache or network access.
These checks need no model files, inference engine, API credentials, or GPU.
Use [docs/harness.md](docs/harness.md) for CLI integration, check coverage, and
how to verify product requirements.

## Make and review a change

Choose a focused issue. Preserve existing songs and artifacts. Add tests for
changed behavior; use fake runtime responses and temporary directories for
application checks. Changes affecting generated music also require an actual
audio sample and a listening check, with the model profile and seed recorded.

Keep issues and PRs in simple English. Include the context and analysis needed
to understand the change, the behavior it delivers, commands/results used to
verify it, and any remaining limitations. Link related issues.

Keep the requirement ledger and [progress notes](docs/progress.md) accurate.
A planned feature is still planned until its acceptance test runs successfully.
Record design changes in the architecture document to give the next contributor
the same context. Git history and the linked issues provide the detailed history.

## Release

### From GitHub (recommended)

Open [Actions → Release](https://github.com/NTTLuke/lux-in-music/actions/workflows/release.yml)
and click **Run workflow**. Select **main**, choose patch/minor/major, or enter an
exact version without `v`. Leave **Preview only** checked for the first run.
The preview validates inputs and runs the portable and offline application
checks, without changing the version or publishing anything.

To publish, run it again with **Preview only** unchecked. It uses the same
`release.sh` command as the local build, creates a version tag on the selected
main commit, builds the ZIP/wheel/sdist/checksums, uploads and verifies them.
The package version is set inside a temporary build copy. The workflow pushes
only the tag and leaves `main`, README and CHANGELOG unchanged.
No personal access token, model download, native engine or GPU is needed.
Only maintainers with workflow access can start it; publication runs from main.
Preview uses a read-only token; only the publication job has `contents: write`.
Official actions are pinned to commits, inputs are validated as data, and
concurrent releases wait rather than cancelling an active publication.

The run uses the selected main commit and refuses publication if main has moved.
Retry from current main in that case. Branch protection can continue requiring
pull requests; release publication does not push to main. If a push or upload
fails after a tag was created, inspect the run and its seven-day `release-files`
artifact before retrying. Do not delete an existing published tag. Preview runs
the full checks; the package build/upload runs on publication.

### From a local machine

A release is also a manual, single-command build from an up-to-date `main`:

```bash
./release.sh minor --dry-run    # preview the notes and the plan
./release.sh minor              # tag, artifacts, GitHub release; main stays unchanged
```

`./release.sh` accepts `major`, `minor`, `patch`, or an explicit version such as
`0.2.0`, and refuses to run on a dirty tree, on another branch, when `main` is not
in sync with `origin/main`, or when the tag already exists. It runs
`scripts/check.py` (add `--full-checks` for the application checks), sets the
package version in a temporary copy, creates a tag on the current `main` commit,
then publishes the source ZIP, wheel, sdist and `SHA256SUMS.txt`, and verifies the
uploaded files. README, CHANGELOG and `main` stay unchanged. Use `--no-push` to
build locally, and `--skip-checks` only when the same revision has already passed
the checks.

Release notes are generated with `git log --first-parent` since the previous tag:
merged pull requests are listed by their PR title, categorized by the branch prefix
(`feat/`, `fix/`, `docs/`, `test/`, `chore/`), and commits made directly on `main`
are listed from their subject line. Keep pull request titles in simple English and
in the same "what changed" style as the existing history, because they become the
public changelog. Use the matching branch prefix so entries land in the right
section.

## Model licenses

The application's MIT license does not change the licenses of model weights,
VAEs, or other downloaded components. Verify those licenses from the actual
release. Model setup must show them and their material restrictions before the
user starts a download. Keep the source link and revision with the model profile.
