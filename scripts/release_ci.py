#!/usr/bin/env python3
"""Validate manual Actions inputs before invoking the shared release command."""

import os
import subprocess
import sys

from release import ROOT, next_version, read_version


def release_command(env):
    if env.get("GITHUB_EVENT_NAME") != "workflow_dispatch" or env.get("GITHUB_REF") != "refs/heads/main":
        raise ValueError("Start the Release workflow manually from main.")
    bump = env.get("RELEASE_BUMP", "")
    if bump not in {"patch", "minor", "major"}:
        raise ValueError("Choose patch, minor or major.")
    version = env.get("RELEASE_VERSION", "").strip()
    # Parse the complete value before passing it as a positional argument.
    next_version(read_version(), version or bump)
    dry_run = env.get("RELEASE_DRY_RUN")
    if dry_run not in {"true", "false"}:
        raise ValueError("Preview must be true or false.")
    command = [str(ROOT / "release.sh"), version or bump, "--full-checks"]
    if dry_run == "true":
        command.append("--dry-run")
    return command


def main():
    try:
        command = release_command(os.environ)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    return subprocess.run(command, cwd=ROOT).returncode


if __name__ == "__main__":
    raise SystemExit(main())
