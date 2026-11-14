"""Seeded-bug catch rate for the reviewer.

`measure` applies each known bug patch to a clean commit in its own detached git
worktree, runs the injected `review` on the seeded commit, and reports the share
of seeds the reviewer rejects. `load_seeds` reads the patches from a directory.
"""

from __future__ import annotations

import json
import sys
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Seed:
    name: str
    patch: str  # unified diff applied on top of the clean commit


def load_seeds(dir: str) -> list[Seed]:
    """Return one Seed per *.patch file in `dir`, named by the file stem."""
    seeds: list[Seed] = []
    for path in sorted(Path(dir).glob("*.patch")):
        seeds.append(Seed(name=path.stem, patch=path.read_text(encoding="utf-8")))
    return seeds


def _git(args: list[str], cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        check=False,
    )


def _require_ok(result: subprocess.CompletedProcess[str], command: str) -> None:
    if result.returncode == 0:
        return
    detail = (result.stderr or result.stdout or "").strip()
    raise RuntimeError(f"{command} failed ({result.returncode}): {detail}")


def _remove_worktree(repo: str, path: str) -> None:
    _git(["worktree", "remove", "--force", path], cwd=repo)
    shutil.rmtree(path, ignore_errors=True)


def measure(
    worktree: str,
    base_sha: str,
    seeds: Sequence[Seed],
    review: Callable[[str, str], bool],
) -> dict:
    """Apply each seed to `base_sha` and count the seeds `review` rejects.

    `review` receives the seeded worktree path and the seeded commit sha, and
    returns True when the reviewer approves the change. A seed whose patch does
    not apply is listed under "skipped" and is not counted.
    """
    caught = 0
    missed: list[str] = []
    skipped: list[str] = []

    for seed in seeds:
        tmp = tempfile.mkdtemp(prefix="watcher-catch-rate-")
        seeded = str(Path(tmp) / "worktree")
        try:
            add = _git(["worktree", "add", "--detach", seeded, base_sha], cwd=worktree)
            _require_ok(add, f"git worktree add {seeded}")
            patch_file = Path(tmp) / f"{seed.name}.patch"
            patch_file.write_text(seed.patch, encoding="utf-8")
            apply = _git(["apply", str(patch_file)], cwd=seeded)
            if apply.returncode != 0:
                skipped.append(seed.name)
                continue
            _require_ok(
                _git(["add", "-A"], cwd=seeded),
                f"git add in {seeded}",
            )
            commit = _git(
                [
                    "-c",
                    "user.name=watcher",
                    "-c",
                    "user.email=watcher@localhost",
                    "commit",
                    "--no-gpg-sign",
                    "-m",
                    f"seed: {seed.name}",
                ],
                cwd=seeded,
            )
            _require_ok(commit, f"git commit in {seeded}")
            sha = _git(["rev-parse", "HEAD"], cwd=seeded).stdout.strip()
            if review(seeded, sha):
                missed.append(seed.name)
            else:
                caught += 1
        finally:
            _remove_worktree(worktree, seeded)
            shutil.rmtree(tmp, ignore_errors=True)

    count = len(seeds) - len(skipped)
    rate = caught / count if count else 0.0
    return {
        "seeds": count,
        "caught": caught,
        "rate": rate,
        "missed": missed,
        "skipped": skipped,
    }


def _review(worktree: str, sha: str) -> bool:
    from watcher import executor  # noqa: PLC0415  (needs ticket 17 on this branch)

    return executor.review(worktree, sha)


def register(subparsers) -> None:
    """Add the `catch-rate` subcommand to `subparsers`."""

    def run(args) -> int:
        from watcher import executor  # noqa: PLC0415
        if not hasattr(executor, "review"):  # fail before any worktree exists
            print("catch-rate: no standalone reviewer in watcher.executor yet", file=sys.stderr)
            return 2
        result = measure(
            args.worktree,
            args.base,
            load_seeds(args.seeds),
            _review,
        )
        print(json.dumps(result, sort_keys=True))
        return 0

    parser = subparsers.add_parser(
        "catch-rate",
        help="apply known bug seeds to a commit and report the share the reviewer rejects",
    )
    parser.add_argument("--worktree", required=True, help="clean worktree to read from")
    parser.add_argument("--base", required=True, help="commit sha the seeds apply on top of")
    parser.add_argument("--seeds", required=True, help="directory of *.patch seed files")
    parser.set_defaults(func=run)
