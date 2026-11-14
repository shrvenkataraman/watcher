"""Git helpers for a lane worktree: exclusive lock, ticket commits, trailer scan."""

from __future__ import annotations

import contextlib
import fcntl
import os
import re
import subprocess
import time

TRAILER = "Watcher-Ticket"
KIND_TRAILER = "Watcher-Kind"
FIX_KIND = "fix"

_POLL_INTERVAL = 0.5
_LOCK_SUFFIX = ".lock"

_SHA = re.compile(r"([0-9a-f]{40})\x00")
_TRAILER_LINE = re.compile(rf"^{TRAILER}:[ \t]*(.*?)[ \t]*$", re.MULTILINE)


def _git(worktree: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", "-C", worktree, *args],
        check=True,
        capture_output=True,
        text=True,
    )


def _common_dir(worktree: str) -> str:
    path = _git(worktree, "rev-parse", "--git-common-dir").stdout.strip()
    if not os.path.isabs(path):
        path = os.path.join(worktree, path)
    return os.path.normpath(path)


def _lock_path(worktree: str) -> str:
    name = os.path.basename(os.path.abspath(worktree))
    return os.path.join(_common_dir(worktree), f"watcher-{name}{_LOCK_SUFFIX}")


@contextlib.contextmanager
def worktree_lock(worktree: str, timeout: float = 60):
    """Hold an exclusive flock on the worktree's lock file.

    Polls every 0.5 s; raises TimeoutError once timeout seconds elapse.
    """
    path = _lock_path(worktree)
    handle = open(path, "a+")
    deadline = time.monotonic() + timeout
    try:
        while True:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                if time.monotonic() >= deadline:
                    raise TimeoutError(
                        f"could not lock worktree {worktree} within {timeout} s"
                    )
                time.sleep(_POLL_INTERVAL)
        yield path
    finally:
        try:
            fcntl.flock(handle, fcntl.LOCK_UN)
        finally:
            handle.close()


def _message(key: str, title: str, kind: str) -> str:
    if kind == "ticket":
        return f"{title}\n\n{TRAILER}: {key}"
    if kind == FIX_KIND:
        return f"fix: {title}\n\n{TRAILER}: {key}\n{KIND_TRAILER}: {FIX_KIND}"
    raise ValueError(f"unknown commit kind: {kind!r}")


def commit_ticket(worktree: str, key: str, title: str, kind: str = "ticket") -> str:
    """Stage everything, commit with a ticket trailer, return the new HEAD sha."""
    message = _message(key, title, kind)
    _git(worktree, "add", "-A")
    _git(worktree, "commit", "-m", message)
    return head(worktree)


def committed_keys(worktree: str, base: str) -> dict[str, str]:
    """Map each ticket key to its commit sha for commits after base.

    Fix commits and commits without a trailer are ignored. When a key has
    several commits, the oldest sha wins.
    """
    out = _git(worktree, "log", "--format=%H%x00%B", f"{base}..HEAD").stdout
    keys: dict[str, str] = {}
    for match in _SHA.finditer(out):
        sha = match.group(1)
        next_match = _SHA.search(out, match.end())
        stop = next_match.start() if next_match is not None else len(out)
        body = out[match.end() : stop]
        if f"{KIND_TRAILER}: {FIX_KIND}" in body:
            continue
        trailer = _TRAILER_LINE.search(body)
        if trailer is None:
            continue
        key = trailer.group(1)
        if not key:
            continue
        keys[key] = sha  # git log walks newest first, so the oldest overwrites
    return keys


def head(worktree: str) -> str:
    """Return the sha of HEAD in the worktree."""
    return _git(worktree, "rev-parse", "HEAD").stdout.strip()
