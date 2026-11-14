"""Draft PR opener: refuse unsafe branches, push, gh pr create, never merge (watcher ticket 21)."""
import os
import subprocess

import pytest

from watcher import gh as ghmod
from watcher.gh import PrRefused, open_pr

FAKE = os.path.join(os.path.dirname(__file__), "fakes", "bin", "gh")


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True, capture_output=True, text=True)


@pytest.fixture
def origin_and_branches(tmp_path, monkeypatch):
    os.chmod(FAKE, 0o755)
    log = tmp_path / "gh.log"
    monkeypatch.setenv("GH_LOG", str(log))
    monkeypatch.setattr(ghmod, "GH", FAKE)
    bare = tmp_path / "origin.git"
    _git(str(tmp_path), "init", "--bare", str(bare))
    # seed a develop branch on the bare origin
    seed = tmp_path / "seed"
    subprocess.run(["git", "clone", str(bare), str(seed)], check=True, capture_output=True)
    _git(str(seed), "checkout", "-b", "develop")
    (seed / "base.txt").write_text("base")
    _git(str(seed), "add", "-A")
    _git(str(seed), "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-m", "base")
    _git(str(seed), "push", "-u", "origin", "develop")

    def make(branch):
        wt = tmp_path / f"wt-{branch.replace('/', '_')}"
        subprocess.run(["git", "clone", str(bare), str(wt)], check=True, capture_output=True)
        _git(str(wt), "checkout", "-B", branch)
        _git(str(wt), "-c", "user.email=t@t", "-c", "user.name=t",
             "commit", "--allow-empty", "-m", "work")
        return str(wt)

    return make, log


def _body_file(tmp_path):
    p = tmp_path / "body.md"
    p.write_text("PR body")
    return str(p)


def test_AC1_feat_branch_pushes_once_and_creates_draft(origin_and_branches, tmp_path):
    make, log = origin_and_branches
    wt = make("feat/thing")
    url = open_pr(wt, "develop", "Add the thing", _body_file(tmp_path))
    assert url == "https://example.test/pull/1"
    lines = log.read_text().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith("pr create --draft --base develop --head feat/thing")
    assert "--title Add the thing" in lines[0]
    assert _git(str(tmp_path / "origin.git"), "rev-parse", "--verify", "refs/heads/feat/thing").returncode == 0


def test_AC2_refused_branches_raise_before_any_push(origin_and_branches, tmp_path):
    make, log = origin_and_branches
    for branch in ("develop", "main", "master", "mywork"):
        wt = make(branch)
        with pytest.raises(PrRefused):
            open_pr(wt, "develop", "t", _body_file(tmp_path))
    assert not log.exists() or log.read_text() == ""


def test_AC3_existing_pr_returns_view_url(origin_and_branches, tmp_path, monkeypatch):
    make, log = origin_and_branches
    monkeypatch.setenv("GH_FAIL_EXIST", "1")
    wt = make("feat/again")
    url = open_pr(wt, "develop", "t", _body_file(tmp_path))
    assert url == "https://example.test/pull/2"
    lines = log.read_text().splitlines()
    assert len(lines) == 2
    assert lines[0].startswith("pr create")
    assert lines[1] == "pr view feat/again --json url -q .url"


def test_AC4_no_argv_ever_contains_merge_or_force(origin_and_branches, tmp_path, monkeypatch):
    make, log = origin_and_branches
    for branch in ("feat/a", "fix/b", "chore/c"):
        open_pr(make(branch), "develop", "t", _body_file(tmp_path))
    monkeypatch.setenv("GH_FAIL_EXIST", "1")
    open_pr(make("feat/d"), "develop", "t", _body_file(tmp_path))
    text = log.read_text()
    assert "merge" not in text
    assert "--force" not in text
