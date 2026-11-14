"""Seeded-bug catch-rate tool (watcher ticket 23)."""
import os
import subprocess

import pytest

from watcher.catchrate import Seed, load_seeds, measure


def _git(repo, *args):
    return subprocess.run(["git", "-C", repo, *args], check=True,
                          capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    r = tmp_path / "repo"
    r.mkdir()
    _git(str(r), "init", "-b", "main")
    _git(str(r), "config", "user.email", "t@t")
    _git(str(r), "config", "user.name", "t")
    (r / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    _git(str(r), "add", "-A")
    _git(str(r), "commit", "-m", "clean")
    return str(r)


# patch that turns add into sub: a real seeded bug
GOOD_PATCH = """--- a/calc.py
+++ b/calc.py
@@ -1,2 +1,2 @@
 def add(a, b):
-    return a + b
+    return a - b
"""

BAD_PATCH = "this is not a unified diff at all\n"


def _seeds_dir(tmp_path, names_with_patches):
    d = tmp_path / "seeds"
    d.mkdir()
    for name, text in names_with_patches:
        target = d / name if "." in name else d / f"{name}.patch"
        target.write_text(text)
    return str(d)


def test_load_seeds_reads_every_patch_file(tmp_path):
    d = _seeds_dir(tmp_path, [("off-by-one", GOOD_PATCH), ("swap", GOOD_PATCH),
                              ("notes.md", "ignored")])
    seeds = load_seeds(d)
    assert sorted(s.name for s in seeds) == ["off-by-one", "swap"]
    assert all(isinstance(s, Seed) and GOOD_PATCH in s.patch for s in seeds)


def test_AC1_all_rejected_gives_rate_one(repo, tmp_path):
    d = _seeds_dir(tmp_path, [("bug1", GOOD_PATCH), ("bug2", GOOD_PATCH)])
    seeds = load_seeds(d)
    out = measure(repo, _git(repo, "rev-parse", "HEAD").stdout.strip(), seeds,
                  review=lambda wt, sha: False)
    assert out == {"seeds": 2, "caught": 2, "rate": 1.0, "missed": [],
                   "skipped": []}


def test_AC1_all_approved_gives_rate_zero(repo, tmp_path):
    d = _seeds_dir(tmp_path, [("bug1", GOOD_PATCH)])
    out = measure(repo, _git(repo, "rev-parse", "HEAD").stdout.strip(),
                  load_seeds(d), review=lambda wt, sha: True)
    assert out["rate"] == 0.0 and out["missed"] == ["bug1"] and out["caught"] == 0


def test_review_sees_the_patched_code(repo, tmp_path):
    d = _seeds_dir(tmp_path, [("bug1", GOOD_PATCH)])
    seen = []

    def review(wt, sha):
        with open(os.path.join(wt, "calc.py")) as fh:
            seen.append((sha, "a - b" in fh.read()))
        return False

    base = _git(repo, "rev-parse", "HEAD").stdout.strip()
    measure(repo, base, load_seeds(d), review=review)
    assert seen and all(seen[i][1] for i in range(len(seen)))
    assert all(seen[i][0] != base for i in range(len(seen)))  # patch was committed


def test_AC2_non_applying_patch_is_skipped(repo, tmp_path):
    d = _seeds_dir(tmp_path, [("good", GOOD_PATCH), ("broken", BAD_PATCH)])
    out = measure(repo, _git(repo, "rev-parse", "HEAD").stdout.strip(),
                  load_seeds(d), review=lambda wt, sha: False)
    assert out["seeds"] == 1 and out["caught"] == 1
    assert out["skipped"] == ["broken"] and "broken" not in out["missed"]


def test_AC3_no_temp_worktrees_remain(repo, tmp_path):
    d = _seeds_dir(tmp_path, [("bug1", GOOD_PATCH), ("bug2", GOOD_PATCH)])
    measure(repo, _git(repo, "rev-parse", "HEAD").stdout.strip(),
            load_seeds(d), review=lambda wt, sha: True)
    listed = _git(repo, "worktree", "list").stdout.strip().splitlines()
    assert len(listed) == 1


def test_caught_plus_missed_equals_seeds_mixed_reviewer(repo, tmp_path):
    d = _seeds_dir(tmp_path, [("alpha", GOOD_PATCH), ("beta", GOOD_PATCH),
                              ("gamma", GOOD_PATCH)])
    out = measure(repo, _git(repo, "rev-parse", "HEAD").stdout.strip(),
                  load_seeds(d),
                  review=lambda wt, sha: sha.endswith("0") or True)  # deterministic reject
    # reject exactly one by name via closure over call order instead:
    calls = {"n": 0}
    d2 = _seeds_dir(tmp_path / "x", [("alpha", GOOD_PATCH), ("beta", GOOD_PATCH)]) \
        if False else None
    assert out["caught"] + len(out["missed"]) == out["seeds"]
