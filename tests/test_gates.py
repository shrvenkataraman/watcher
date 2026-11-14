"""GitGate: lane worktrees and verify without hk (ticket 15)."""
import os
import subprocess

import pytest
from hypothesis import given, settings, strategies as st

from watcher.ports import Gate, GateResult


def _git(*args, cwd):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True).stdout


@pytest.fixture
def root(tmp_path):
    r = tmp_path / "root"
    repo = r / "repos" / "app"
    repo.mkdir(parents=True)
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    (repo / "f.txt").write_text("x")
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "init", cwd=repo)
    return str(r)


def _gate():
    from watcher.gates import GitGate
    return GitGate()


def _count(root):
    return len(_git("worktree", "list", cwd=os.path.join(root, "repos", "app")).strip().splitlines())


def test_AC1_ensure_lane_creates_branch_worktree_and_is_idempotent(root):
    g = _gate()
    path = g.ensure_lane("p1", "app", "main", "true", root)
    assert path == os.path.join(root, "features", "p1", "app") == g.lane_worktree(root, "p1", "app")
    assert os.path.isfile(os.path.join(path, "f.txt"))
    assert _git("rev-parse", "--abbrev-ref", "HEAD", cwd=path).strip() == "feat/p1"
    assert open(os.path.join(path, ".agent", "check")).read().strip() == "true"
    before = _git("rev-parse", "HEAD", cwd=path)
    assert g.ensure_lane("p1", "app", "main", "false", root) == path
    assert _git("rev-parse", "HEAD", cwd=path) == before
    assert open(os.path.join(path, ".agent", "check")).read().strip() == "true"


def test_AC1_custom_dirs(tmp_path, root):
    from watcher.gates import GitGate
    wt = tmp_path / "wts"
    g = GitGate(repos_dir=os.path.join(root, "repos"), worktrees_dir=str(wt))
    assert g.lane_worktree("ignored", "p2", "app") == str(wt / "p2" / "app")
    assert g.ensure_lane("p2", "app", "main", "true", "ignored") == str(wt / "p2" / "app")


@settings(max_examples=5, deadline=None)
@given(n=st.integers(min_value=1, max_value=4))
def test_AC1_property_idempotent_one_worktree(n, tmp_path_factory):
    r = tmp_path_factory.mktemp("r")
    repo = r / "repos" / "app"
    repo.mkdir(parents=True)
    _git("init", "-q", "-b", "main", cwd=repo)
    _git("config", "user.email", "t@t", cwd=repo)
    _git("config", "user.name", "t", cwd=repo)
    (repo / "f").write_text("x")
    _git("add", ".", cwd=repo)
    _git("commit", "-q", "-m", "i", cwd=repo)
    g = _gate()
    for _ in range(n):
        g.ensure_lane("p", "app", "main", "true", str(r))
    assert _count(str(r)) == 2


def test_AC2_verify_ok_and_fail_with_tail(tmp_path):
    g = _gate()
    wt = tmp_path / "wt"
    (wt / ".agent").mkdir(parents=True)
    (wt / ".agent" / "check").write_text("true\n")
    res = g.verify(str(wt))
    assert isinstance(res, GateResult) and res.ok
    (wt / ".agent" / "check").write_text("echo boom; false\n")
    res = g.verify(str(wt))
    assert not res.ok and "boom" in res.tail


def test_AC2_verify_tail_is_last_40_lines(tmp_path):
    g = _gate()
    wt = tmp_path / "wt"
    (wt / ".agent").mkdir(parents=True)
    (wt / ".agent" / "check").write_text("seq 1 100; false\n")
    res = g.verify(str(wt))
    lines = res.tail.strip().splitlines()
    assert len(lines) <= 40 and lines[-1] == "100" and "61" in lines and "60" not in lines and "1" not in lines


def test_AC3_review_always_ok(tmp_path):
    res = _gate().review(str(tmp_path))
    assert res == GateResult(True, "no review gate")


def test_AC4_is_gate():
    assert isinstance(_gate(), Gate)
