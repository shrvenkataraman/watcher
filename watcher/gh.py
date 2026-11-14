"""Draft PR opener: push a lane branch, open a draft PR, never merge (ticket 21)."""

from __future__ import annotations

import os
import subprocess

GH = os.environ.get("WATCHER_GH", "gh")

PROTECTED = ("main", "master", "develop")
ALLOWED_PREFIXES = ("feat/", "fix/", "chore/")
ALREADY_EXISTS = "already exists"


class PrRefused(RuntimeError):
    """Raised when the lane branch must not leave the machine."""


def _branch(worktree: str) -> str:
    result = subprocess.run(
        ["git", "-C", worktree, "rev-parse", "--abbrev-ref", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _check_branch(branch: str, base: str) -> None:
    """Refuse a base branch, a protected branch, or an unprefixed branch."""
    if branch == base:
        raise PrRefused(f"refusing to open a PR from the base branch {branch!r}")
    if branch in PROTECTED:
        raise PrRefused(f"refusing to open a PR from protected branch {branch!r}")
    if not branch.startswith(ALLOWED_PREFIXES):
        raise PrRefused(
            f"refusing to open a PR from {branch!r}: "
            f"branch must start with one of {', '.join(ALLOWED_PREFIXES)}"
        )


def _push(worktree: str, branch: str) -> None:
    subprocess.run(
        ["git", "-C", worktree, "push", "-u", "origin", branch],
        check=True,
        capture_output=True,
        text=True,
    )


def _gh(worktree: str, args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [GH, *args],
        cwd=worktree,
        capture_output=True,
        text=True,
        check=False,
    )


def _last_line(stdout: str) -> str:
    lines = [line.strip() for line in stdout.splitlines() if line.strip()]
    return lines[-1] if lines else ""


def open_pr(worktree: str, base: str, title: str, body_file: str) -> str:
    """Push the lane branch and open a draft PR against base; return the PR URL.

    Raises PrRefused before any push when the branch is unsafe to publish.
    """
    branch = _branch(worktree)
    _check_branch(branch, base)
    _push(worktree, branch)

    created = _gh(
        worktree,
        [
            "pr",
            "create",
            "--draft",
            "--base",
            base,
            "--head",
            branch,
            "--title",
            title,
            "--body-file",
            body_file,
        ],
    )
    output = f"{created.stdout}\n{created.stderr}".lower()
    if created.returncode != 0 and ALREADY_EXISTS not in output:
        raise RuntimeError(f"gh pr create failed for {branch}: {output.strip()}")

    if created.returncode != 0:
        viewed = _gh(worktree, ["pr", "view", branch, "--json", "url", "-q", ".url"])
        if viewed.returncode != 0:
            raise RuntimeError(
                f"gh pr view failed for {branch}: "
                f"{f'{viewed.stdout}\n{viewed.stderr}'.strip()}"
            )
        return _last_line(viewed.stdout)

    return _last_line(created.stdout)
