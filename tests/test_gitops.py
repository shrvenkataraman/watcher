"""Git helpers: lock, ticket commits with trailers, trailer scan (watcher ticket 13)."""
import subprocess
import sys
import time

import pytest

from watcher.gitops import TRAILER, commit_ticket, committed_keys, head, worktree_lock


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "wt"
    r.mkdir()
    def git(*args):
        return subprocess.run(["git", "-C", str(r), *args], check=True, capture_output=True, text=True)
    git("init", "-b", "main")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (r / "base.txt").write_text("base")
    git("add", "-A")
    git("commit", "-m", "base")
    base_sha = head(str(r))
    return str(r), git, base_sha


def _write(path, name):
    (path / name).write_text(name)


def test_AC1_commit_ticket_creates_one_trailer_commit_and_returns_sha(repo, tmp_path):
    wt, git, base = repo
    from pathlib import Path
    _write(Path(wt), "f1.txt")
    sha = commit_ticket(wt, "quark-kit/01", "Add f1")
    assert sha == head(wt)
    body = git("log", "-1", "--format=%B").stdout
    assert body.strip().endswith(f"{TRAILER}: quark-kit/01")
    assert git("rev-list", "--count", f"{base}..HEAD").stdout.strip() == "1"


def test_AC1_fix_kind_adds_fix_trailer(repo, tmp_path):
    wt, git, _ = repo
    from pathlib import Path
    _write(Path(wt), "f2.txt")
    commit_ticket(wt, "quark-kit/01", "Address findings", kind="fix")
    body = git("log", "-1", "--format=%B").stdout
    assert f"{TRAILER}: quark-kit/01" in body and "Watcher-Kind: fix" in body


def test_AC2_committed_keys_maps_tickets_and_ignores_fixes_and_plain_commits(repo, tmp_path):
    wt, git, base = repo
    from pathlib import Path
    expected = {}
    for i, (key, kind) in enumerate([("a/01", "ticket"), ("a/02", "ticket"),
                                     ("a/01", "fix"), ("a/03", "ticket")]):
        _write(Path(wt), f"c{i}.txt")
        sha = commit_ticket(wt, key, f"commit {i}", kind=kind)
        if kind == "ticket":
            expected.setdefault(key, sha)
    _write(Path(wt), "plain.txt")
    git("add", "-A")
    git("commit", "-m", "no trailer here")
    assert committed_keys(wt, base) == expected


def test_AC3_lock_contention_raises_timeout(repo):
    wt, git, _ = repo
    import pathlib
    code = (
        "import sys, time\n"
        f"sys.path.insert(0, {str(pathlib.Path(__file__).resolve().parents[1])!r})\n"
        "from watcher.gitops import worktree_lock\n"
        f"lock = worktree_lock({wt!r}, timeout=30)\n"
        "lock.__enter__()\n"
        "print('held', flush=True)\n"
        "time.sleep(5)\n"
    )
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    assert proc.stdout.readline().strip() == "held"
    try:
        t0 = time.monotonic()
        with pytest.raises(TimeoutError):
            with worktree_lock(wt, timeout=0.5):
                pass
        assert time.monotonic() - t0 >= 0.5
    finally:
        proc.kill()
        proc.wait()


def test_AC4_failing_pre_commit_hook_raises(repo):
    wt, git, _ = repo
    from pathlib import Path
    hook = Path(wt) / ".git" / "hooks" / "pre-commit"
    hook.write_text("#!/bin/sh\nexit 1\n")
    hook.chmod(0o755)
    _write(Path(wt), "blocked.txt")
    with pytest.raises(subprocess.CalledProcessError):
        commit_ticket(wt, "a/09", "blocked commit")
