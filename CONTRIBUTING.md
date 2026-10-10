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

## Model licenses

The application's MIT license does not change the licenses of model weights,
VAEs, or other downloaded components. Verify those licenses from the actual
release. Model setup must show them and their material restrictions before the
user starts a download. Keep the source link and revision with the model profile.
