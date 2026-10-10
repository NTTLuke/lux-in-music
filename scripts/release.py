#!/usr/bin/env python3
"""Create a versioned GitHub release for Lux In Music in one command.

    ./release.sh patch                 # or minor | major | 0.1.2
    ./release.sh minor --dry-run       # show everything, change nothing

Steps, in order:

1. preflight: on `main`, clean tree, in sync with `origin/main`, tag still free
2. repository checks (`scripts/check.py`, plus application checks with --full-checks)
3. version bump in `pyproject.toml`
4. `CHANGELOG.md` entry built from the merged pull requests and main commits
5. `README.md` "Releases and changelog" block refreshed between its markers
6. release commit and annotated tag, then `main` and the tag are pushed
7. artifacts built from the tag: source ZIP, wheel, sdist, `SHA256SUMS.txt`
8. GitHub release created with the notes and the artifacts, then verified

Options: --dry-run, --skip-checks, --full-checks, --no-push, --no-build, -v.

Set LUX_RELEASE_SLUG=owner/repo to override the repository used in the release
links when `origin` is not a GitHub remote (a mirror, a local clone, a fork).
"""

from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import NoReturn

ROOT = Path(__file__).resolve().parents[1]
PYPROJECT = ROOT / "pyproject.toml"
README = ROOT / "README.md"
CHANGELOG = ROOT / "CHANGELOG.md"
DIST = ROOT / "dist"
BRANCH = "main"
PROJECT_NAME = "Lux In Music"

README_START = "<!-- release:start -->"
README_END = "<!-- release:end -->"

SECTION_ORDER = ["Added", "Changed", "Fixed", "Documentation", "Tests and checks", "Other"]
COUNT_WORDS = {
    "Added": ("new feature", "new features"),
    "Fixed": ("fix", "fixes"),
    "Documentation": ("documentation update", "documentation updates"),
    "Tests and checks": ("test and check update", "test and check updates"),
}

BRANCH_SECTIONS = {
    "feat": "Added",
    "feature": "Added",
    "fix": "Fixed",
    "bugfix": "Fixed",
    "docs": "Documentation",
    "doc": "Documentation",
    "test": "Tests and checks",
    "tests": "Tests and checks",
    "perf": "Changed",
    "refactor": "Changed",
    "chore": "Changed",
    "build": "Changed",
    "ci": "Changed",
    "style": "Changed",
}

SKIP_SUBJECTS = re.compile(
    r"^(merge (branch|remote|tag)|release v?\d|bump version|wip\b|changelog|"
    r"initial commit|first commit|root commit)",
    re.IGNORECASE,
)

VERBOSE = False


# ---------------------------------------------------------------- output helpers


def log(message: str) -> None:
    print(message, flush=True)


def step(number: int, total: int, message: str) -> None:
    log(f"\n[{number}/{total}] {message}")


def detail(message: str) -> None:
    if VERBOSE:
        log(f"       {message}")


def die(message: str, code: int = 1) -> NoReturn:
    log("")
    log(f"ERROR: {message}")
    sys.exit(code)


def run(
    args: list[str],
    check: bool = True,
    echo: bool = False,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess:
    result = subprocess.run(
        args, cwd=str(cwd or ROOT), text=True, capture_output=True, check=False
    )
    detail("$ " + " ".join(args))
    if echo and result.stdout.strip():
        log(result.stdout.rstrip())
    if check and result.returncode != 0:
        output = (result.stderr or result.stdout or "").strip()
        die(f"command failed ({result.returncode}): {' '.join(args)}\n{output}")
    return result


def git(*args: str, check: bool = True) -> str:
    return run(["git", *args], check=check).stdout.strip()


def changed_files() -> list[str]:
    """Paths reported by `git status --porcelain`, whatever its column spacing."""
    paths: list[str] = []
    # Not git(): its .strip() would eat the leading status column of the first line.
    for line in run(["git", "status", "--porcelain"]).stdout.splitlines():
        if not line.strip():
            continue
        match = re.match(r"^.{2}\s+(.+)$", line)
        paths.append((match.group(1) if match else line).strip().strip('"'))
    return sorted(paths)


# ---------------------------------------------------------------- version helpers


def read_version() -> str:
    text = PYPROJECT.read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    if not match:
        die(f"no `version = \"...\"` line found in {PYPROJECT.name}")
    return match.group(1)


def parse_version(value: str) -> tuple[int, int, int]:
    match = re.fullmatch(r"(\d+)\.(\d+)\.(\d+)", value.strip())
    if not match:
        die(f"version `{value}` is not in MAJOR.MINOR.PATCH form")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def next_version(current: str, bump: str) -> str:
    major, minor, patch = parse_version(current)
    bump = bump.strip()
    if bump in {"major", "minor", "patch"}:
        if bump == "major":
            return f"{major + 1}.0.0"
        if bump == "minor":
            return f"{major}.{minor + 1}.0"
        return f"{major}.{minor}.{patch + 1}"
    parse_version(bump)
    if parse_version(bump) < (major, minor, patch):
        die(f"requested version {bump} is older than the current {current}")
    return bump


def bump_pyproject(new_version: str, current: str) -> None:
    if new_version == current:
        detail(f"pyproject.toml already declares {new_version}; nothing to change")
        return
    text = PYPROJECT.read_text(encoding="utf-8")
    updated, count = re.subn(
        r'(?m)^version\s*=\s*"[^"]+"', f'version = "{new_version}"', text, count=1
    )
    if count != 1:
        die("could not update the version line in pyproject.toml")
    PYPROJECT.write_text(updated, encoding="utf-8")


# ---------------------------------------------------------------- history helpers


def last_tag() -> str | None:
    result = run(["git", "describe", "--tags", "--abbrev=0", "--match", "v[0-9]*"], check=False)
    tag = result.stdout.strip()
    return tag or None


def repo_slug() -> str:
    """`owner/repo` for the release links, from origin or LUX_RELEASE_SLUG."""
    override = os.environ.get("LUX_RELEASE_SLUG", "").strip()
    if override:
        detail(f"repository from LUX_RELEASE_SLUG: {override}")
        return override
    url = git("remote", "get-url", "origin")
    match = re.search(r"github\.com[:/]([^/]+/[^/.]+?)(?:\.git)?$", url)
    if not match:
        die(f"cannot read the GitHub owner/repository from remote `{url}`")
    return match.group(1)


def collect_changes(previous: str | None) -> list[dict[str, object]]:
    """One entry per merged pull request, plus the commits made straight to main."""
    span = f"{previous}..HEAD" if previous else "HEAD"
    raw = git(
        "log",
        "--first-parent",
        "--no-color",
        "--format=%h\x1f%s\x1f%b\x1e",
        span,
    )
    entries: list[dict[str, object]] = []
    for chunk in raw.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        fields = chunk.split("\x1f")
        short, subject = fields[0].strip(), fields[1].strip()
        body = fields[2].strip() if len(fields) > 2 else ""

        merge = re.match(r"Merge pull request #(\d+) from [^/]+/(.+)", subject)
        if merge:
            pull, branch = int(merge.group(1)), merge.group(2).strip()
            title = body.splitlines()[0].strip() if body.strip() else branch_title(branch)
            prefix = branch.split("/")[0].lower()
            entries.append(
                {
                    "title": title,
                    "section": BRANCH_SECTIONS.get(prefix, "Changed"),
                    "pull": pull,
                    "sha": short,
                }
            )
            continue

        if SKIP_SUBJECTS.match(subject) or not subject:
            continue
        entries.append(
            {"title": subject, "section": guess_section(subject), "pull": None, "sha": short}
        )
    return entries


def branch_title(branch: str) -> str:
    """Readable title from a branch name, used when a merge commit has no body."""
    words = re.split(r"[/_\-]+", branch.strip())
    if len(words) > 1 and words[0].lower() in BRANCH_SECTIONS:
        words = words[1:]
    title = " ".join(word for word in words if word).strip()
    return title[:1].upper() + title[1:] if title else branch


def guess_section(subject: str) -> str:
    text = subject.lower()
    if re.search(r"\b(fix|fixes|fixed|repair|correct|corrects|resolve|resolves|prevent|avoids?|bug)\b", text):
        return "Fixed"
    if re.search(r"\b(doc|docs|document|documents|documented|readme|guide|instructions?)\b", text):
        return "Documentation"
    if re.search(r"\b(test|tests|tested|check|checks|harness|coverage)\b", text):
        return "Tests and checks"
    if re.search(r"\b(add|adds|added|introduce|introduces|support|supports|enable|allows?|implement|implements|new)\b", text):
        return "Added"
    return "Changed"


def group(entries: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    grouped: dict[str, list[dict[str, object]]] = {name: [] for name in SECTION_ORDER}
    for entry in entries:
        grouped[str(entry["section"])].append(entry)
    return grouped


def counts_line(grouped: dict[str, list[dict[str, object]]]) -> str:
    parts: list[str] = []
    for name in ("Added", "Fixed", "Documentation", "Tests and checks"):
        amount = len(grouped.get(name, []))
        if not amount:
            continue
        single, plural = COUNT_WORDS.get(name, (name.lower(), name.lower()))
        parts.append(f"{amount} {single if amount == 1 else plural}")
    other = len(grouped.get("Changed", [])) + len(grouped.get("Other", []))
    if other:
        parts.append(f"{other} other change" + ("s" if other != 1 else ""))
    if not parts:
        return "No user-facing changes recorded."
    return "This release includes " + ", ".join(parts[:-1]) + (" and " if len(parts) > 1 else "") + parts[-1] + "."


def bullets(entries: list[dict[str, object]], slug: str) -> list[str]:
    lines: list[str] = []
    for entry in entries:
        line = f"- {str(entry['title']).rstrip('.')}"
        if entry["pull"]:
            line += f" ([#{entry['pull']}](https://github.com/{slug}/pull/{entry['pull']}))"
        lines.append(line)
    return lines


def render_sections(entries: list[dict[str, object]], slug: str, heading: str = "###") -> list[str]:
    grouped = group(entries)
    lines: list[str] = []
    for name in SECTION_ORDER:
        if not grouped[name]:
            continue
        lines.append(f"{heading} {name}")
        lines.append("")
        lines.extend(bullets(grouped[name], slug))
        lines.append("")
    return lines


def changelog_entry(version: str, release_date: str, entries: list[dict[str, object]], slug: str, previous: str | None) -> str:
    lines = [f"## [{version}] - {release_date}", ""]
    if previous is None:
        lines += ["First published release of Lux In Music.", ""]
    lines += render_sections(entries, slug)
    return "\n".join(lines).rstrip() + "\n"


def update_changelog(entry: str, version: str) -> None:
    """Write the entry, replacing an existing section for the same version.

    Replacing rather than always inserting keeps a re-run after an interrupted
    release from duplicating the section.
    """
    header = (
        "# Changelog\n\n"
        "All notable changes to Lux In Music are documented in this file, one\n"
        "section per GitHub release, newest first.\n\n"
    )
    text = CHANGELOG.read_text(encoding="utf-8") if CHANGELOG.exists() else header
    existing = re.search(rf"(?m)^## \[{re.escape(version)}\][^\n]*\n", text)
    if existing:
        following = re.search(r"(?m)^## \[", text[existing.end() :])
        end = existing.end() + (following.start() if following else len(text) - existing.end())
        text = text[: existing.start()] + entry + "\n" + text[end:].lstrip("\n")
        detail(f"replaced the existing {version} entry in CHANGELOG.md")
    else:
        position = text.find("\n## [")
        if position == -1:
            text = text.rstrip() + "\n\n" + entry
        else:
            text = text[: position + 1] + entry + "\n" + text[position + 1 :]
    CHANGELOG.write_text(text.rstrip() + "\n", encoding="utf-8")


# ---------------------------------------------------------------- README helpers


def release_block(version: str, release_date: str, grouped: dict[str, list[dict[str, object]]], slug: str) -> str:
    base = f"https://github.com/{slug}"
    tag = f"{base}/releases/tag/v{version}"
    zip_name = f"lux-in-music-v{version}.zip"
    lines = [
        README_START,
        f"**Latest release: [v{version}]({tag})** · {release_date}",
        "",
        f"- **Download (recommended):** [`{zip_name}`]({base}/releases/download/v{version}/{zip_name})"
        " — the app source, ready to extract",
        f"- Also attached: `lux_in_music-{version}-py3-none-any.whl`,"
        f" `lux_in_music-{version}.tar.gz`, `SHA256SUMS.txt`",
        f"- [Release notes]({tag}) · [All releases]({base}/releases) · [CHANGELOG.md](CHANGELOG.md)",
        "",
        counts_line(grouped) + " See [CHANGELOG.md](CHANGELOG.md) for the full list.",
        README_END,
    ]
    return "\n".join(lines)


def update_readme(version: str, block: str, previous: str | None, slug: str) -> None:
    text = README.read_text(encoding="utf-8")
    if README_START in text and README_END in text:
        head, rest = text.split(README_START, 1)
        _, tail = rest.split(README_END, 1)
        text = head + block + tail
    else:
        section = f"""## Releases and changelog

Lux In Music is published as numbered [releases](https://github.com/{slug}/releases).
Download the ZIP of the latest release, extract it, and continue with the steps
below: the install and launch instructions are the same.

{block}

"""
        marker = "## Install on a Mac"
        if marker in text:
            text = text.replace(marker, section + marker, 1)
        else:
            text = text.rstrip() + "\n\n" + section
    README.write_text(text, encoding="utf-8")
    if previous is None:
        detail("README release section created")


# ---------------------------------------------------------------- build helpers


def build_artifacts(version: str, tag: str, slug: str, notes_path: Path, skip: bool) -> list[Path]:
    DIST.mkdir(exist_ok=True)
    zip_path = DIST / f"lux-in-music-v{version}.zip"
    wheel = DIST / f"lux_in_music-{version}-py3-none-any.whl"
    sdist = DIST / f"lux_in_music-{version}.tar.gz"
    for stale in (zip_path, wheel, sdist):
        if stale.exists():
            stale.unlink()
            detail(f"removed previous {stale.name}")

    if skip:
        detail("artifact build skipped (--no-build)")
        return []

    run(
        [
            "git",
            "archive",
            "--format=zip",
            f"--prefix=lux-in-music-{version}/",
            "-o",
            str(zip_path),
            tag,
        ]
    )
    run(["uv", "build", "--out-dir", str(DIST)], echo=True)
    missing = [path.name for path in (wheel, sdist) if not path.exists()]
    if missing:
        die(f"uv build did not produce: {', '.join(missing)}")

    artifacts = [zip_path, wheel, sdist]
    sums = DIST / "SHA256SUMS.txt"
    sums.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in artifacts), encoding="utf-8"
    )
    artifacts.append(sums)
    for path in artifacts:
        log(f"       {path.name} ({path.stat().st_size / 1024:.0f} KB)")
    return artifacts


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def release_notes(version: str, release_date: str, entries: list[dict[str, object]], slug: str, previous: str | None) -> str:
    base = f"https://github.com/{slug}"
    lines = [f"# {PROJECT_NAME} v{version}", "", f"Released {release_date}.", ""]
    if previous is None:
        lines += ["First published release.", ""]
    lines += [counts_line(group(entries)), ""]
    lines += render_sections(entries, slug)
    lines += [
        "## Downloads",
        "",
        f"- `lux-in-music-v{version}.zip` — the app source. Extract it, then run"
        " `./studio.sh` in the extracted folder.",
        f"- `lux_in_music-{version}-py3-none-any.whl`, `lux_in_music-{version}.tar.gz` — the Python package.",
        "- `SHA256SUMS.txt` — checksums of the three files above.",
        "",
        f"Install guide: [Install on a Mac]({base}/blob/{BRANCH}/README.md#install-on-a-mac).",
        f"Full history: [CHANGELOG.md]({base}/blob/{BRANCH}/CHANGELOG.md).",
        "",
        "If Terminal reports `Permission denied` after extracting the ZIP, run:",
        "",
        "```bash",
        "chmod +x studio.sh scripts/setup.sh \"Lux In Music.command\"",
        "```",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------- checks


def run_checks(full: bool, skip: bool) -> None:
    if skip:
        log("       repository checks skipped (--skip-checks)")
        return
    run(["python3", "scripts/check.py"], echo=True)
    if full:
        run(["uv", "sync", "--frozen"], echo=True)
        run([str(ROOT / ".venv" / "bin" / "python"), "scripts/check.py", "--full"], echo=True)
    else:
        log("       application checks (--full-checks) not requested")


# ---------------------------------------------------------------- main


def main() -> None:
    global VERBOSE

    parser = argparse.ArgumentParser(
        prog="release.sh",
        description="Build and publish a versioned GitHub release for Lux In Music.",
        add_help=True,
    )
    parser.add_argument("bump", help="major, minor, patch, or an explicit version such as 0.2.0")
    parser.add_argument("--dry-run", action="store_true", help="show every step, change nothing")
    parser.add_argument("--skip-checks", action="store_true", help="do not run scripts/check.py")
    parser.add_argument("--full-checks", action="store_true", help="also run the application checks")
    parser.add_argument("--no-push", action="store_true", help="commit, tag and build locally only")
    parser.add_argument("--no-build", action="store_true", help="skip ZIP/wheel/sdist, publish notes only")
    parser.add_argument("-v", "--verbose", action="store_true", help="print every command")
    args = parser.parse_args()

    VERBOSE = args.verbose
    slug = repo_slug()
    current = read_version()
    version = next_version(current, args.bump)
    tag = f"v{version}"
    release_date = _dt.date.today().isoformat()
    pretty_date = _dt.date.today().strftime("%-d %B %Y") if sys.platform != "win32" else release_date
    publish = not args.dry_run and not args.no_push

    if version == current:
        log(f"{PROJECT_NAME} release: v{version}, the current unreleased version  ({slug})")
    else:
        log(f"{PROJECT_NAME} release: {current} -> {version}  ({slug})")
    if args.dry_run:
        log("Dry run: no file, commit, tag or release is created.")
    total = 7 if args.dry_run else 8

    # 1 ---------------------------------------------------------------- preflight
    step(1, total, "Check the repository state")
    if not (ROOT / "pyproject.toml").exists():
        die(f"pyproject.toml not found in {ROOT}")
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:
        die(f"releases are built from `{BRANCH}`; the current branch is `{branch}`")
    dirty = changed_files()
    if dirty:
        die("the working tree is not clean:\n  " + "\n  ".join(dirty))
    detail("working tree clean")
    if run(["git", "check-ignore", "-q", "dist/"], check=False).returncode != 0:
        die("dist/ is not ignored by Git; the release artifacts would be committed")
    if run(["git", "rev-parse", "-q", "--verify", f"refs/tags/{tag}"], check=False).returncode == 0:
        die(f"tag {tag} already exists locally; choose another version")
    run(["git", "fetch", "origin", BRANCH], echo=False)
    local_head, remote_head = git("rev-parse", "HEAD"), git("rev-parse", f"origin/{BRANCH}")
    if local_head != remote_head:
        behind = git("rev-list", "--count", f"HEAD..origin/{BRANCH}")
        die(
            f"`{BRANCH}` is not in sync with origin/{BRANCH} ({behind} commit(s) behind, "
            "or local commits not pushed). Pull or push first."
        )
    detail(f"main in sync with origin ({local_head[:7]})")
    remote_tag = run(["git", "ls-remote", "--tags", "origin", tag], check=False).stdout.strip()
    if remote_tag:
        die(f"tag {tag} already exists on origin")
    for key in ("user.name", "user.email"):
        if run(["git", "config", "--get", key], check=False).returncode != 0:
            die(
                f"Git has no `{key}`; set it with "
                f'`git config --global {key} "..."` before releasing'
            )
    for tool in ("git", "uv"):
        if run(["sh", "-c", f"command -v {tool}"], check=False).returncode != 0:
            die(f"`{tool}` is required but was not found in PATH")
    if publish and run(["sh", "-c", "command -v gh"], check=False).returncode != 0:
        die("`gh` (GitHub CLI) is required to publish the release")
    if publish and run(["gh", "auth", "status"], check=False).returncode != 0:
        die("`gh auth status` reports no usable GitHub login; run `gh auth login`")

    # 2 ---------------------------------------------------------------- history
    step(2, total, "Collect the changes since the last release")
    previous = last_tag()
    if previous is None:
        log("       no previous release tag: this is the first release")
    else:
        log(f"       range: {previous}..HEAD")
    entries = collect_changes(previous)
    if not entries:
        die(f"no commits found since {previous or 'the start of history'}; nothing to release")
    grouped = group(entries)
    log(
        "       "
        + ", ".join(f"{len(grouped[name])} {name.lower()}" for name in SECTION_ORDER if grouped[name])
    )
    for name in SECTION_ORDER:
        for entry in grouped[name]:
            log(f"         {name}: {entry['title']}")

    # 3 ---------------------------------------------------------------- checks
    step(3, total, "Run the repository checks")
    run_checks(args.full_checks, args.skip_checks)
    after_checks = changed_files()
    if after_checks:
        die("the checks left the working tree dirty:\n  " + "\n  ".join(after_checks))

    # 4 ---------------------------------------------------------------- files
    step(4, total, "Write the release files")
    entry = changelog_entry(version, release_date, entries, slug, previous)
    block = release_block(version, pretty_date, grouped, slug)
    notes = release_notes(version, release_date, entries, slug, previous)
    expected = ["pyproject.toml", "CHANGELOG.md", "README.md"]
    if args.dry_run:
        if version == current:
            log(f"       pyproject.toml: version {version} (already current, no change)")
        else:
            log(f"       pyproject.toml: version {current} -> {version}")
        log("       CHANGELOG.md entry:\n")
        log("\n".join("         " + line for line in entry.rstrip().splitlines()))
        log("\n       README.md block:\n")
        log("\n".join("         " + line for line in block.splitlines()))
        log("\n       dist/RELEASE_NOTES.md:\n")
        log("\n".join("         " + line for line in notes.rstrip().splitlines()))
        log("")
        log(f"       artifacts for {tag}: dist/lux-in-music-{tag}.zip, dist/RELEASE_NOTES.md")
        log(f"       next real run: ./release.sh {args.bump}   (pushes {BRANCH} and {tag})")
        return

    DIST.mkdir(exist_ok=True)
    notes_path = DIST / f"RELEASE_NOTES-{tag}.md"
    notes_path.write_text(notes, encoding="utf-8")
    bump_pyproject(version, current)
    update_changelog(entry, version)
    update_readme(version, block, previous, slug)
    changed = changed_files()
    unexpected = [path for path in changed if path not in expected]
    if unexpected:
        die("unexpected changes before the release commit:\n  " + "\n  ".join(unexpected))
    log(f"       updated: {', '.join(changed)}")

    # 5 ---------------------------------------------------------------- commit
    step(5, total, "Commit and tag")
    run(["git", "add", *expected])
    run(["git", "commit", "-m", f"Release v{version}", "-m", counts_line(grouped)])
    run(["git", "tag", "-a", tag, "-m", f"{PROJECT_NAME} v{version}"])
    log(f"       commit {git('rev-parse', '--short', 'HEAD')} tagged {tag}")

    # 6 ---------------------------------------------------------------- build
    step(6, total, "Build the release artifacts")
    artifacts = build_artifacts(version, tag, slug, notes_path, args.no_build)

    # 7 ---------------------------------------------------------------- push
    step(7, total, "Push the commit and the tag")
    if args.no_push:
        log("       push skipped (--no-push)")
    else:
        run(["git", "push", "origin", BRANCH], echo=True)
        run(["git", "push", "origin", tag], echo=True)
        log(f"       {BRANCH} and {tag} are on origin")

    # 8 ---------------------------------------------------------------- release
    step(8, total, "Create the GitHub release")
    if not publish:
        log("       release not created (--no-push)")
        log(f"\n       local artifacts: {', '.join(path.name for path in artifacts) or 'none'}")
        return

    command = [
        "gh",
        "release",
        "create",
        tag,
        "--title",
        f"{PROJECT_NAME} v{version}",
        "--notes-file",
        str(notes_path),
        "--verify-tag",
        "--latest",
        *[str(path) for path in artifacts],
    ]
    run(command, echo=True)
    verify_release(tag, slug, version, artifacts)


def verify_release(tag: str, slug: str, version: str, artifacts: list[Path]) -> None:
    log("")
    log("       verifying the published release")
    result = run(["gh", "release", "view", tag, "--json", "tagName,name,isDraft,url,assets"])
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        die("could not read the release details from gh")
    if data.get("isDraft"):
        die(f"release {tag} is still a draft and cannot be downloaded")
    assets = {asset["name"]: asset.get("size", 0) for asset in data.get("assets", [])}
    missing = [path.name for path in artifacts if path.name not in assets]
    empty = [name for name, size in assets.items() if not size]
    log(f"       url: {data.get('url')}")
    for name, size in sorted(assets.items()):
        log(f"       asset {name} ({size / 1024:.0f} KB)")
    if missing or empty:
        log("")
        log("WARNING: the release exists but its assets are incomplete.")
        for name in missing:
            log(f"  missing: {name}")
        for name in empty:
            log(f"  empty: {name}")
        log("Fix with: gh release upload " + tag + " dist/<file> --clobber")
        sys.exit(2)
    log("")
    log(f"OK: {tag} published with {len(assets)} downloadable files")
    log(f"       {data.get('url')}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log("\ninterrupted")
        sys.exit(130)
