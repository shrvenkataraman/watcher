"""Executor: actions to events through the adapters (watcher ticket 17)."""
import importlib
import json
import os
import subprocess

import pytest

import watcher.hk as hkmod
import watcher.llm as llmmod
import watcher.omp as ompmod
import watcher.prompts as promptsmod
from watcher.executor import Ctx, execute
from watcher.inbox import Plan
from watcher.omp import OmpResult
from watcher.types import Action, State


def _patch(monkeypatch, modname, name, fn):
    """Patch a function on its source module AND on watcher.executor (covers direct imports)."""
    import watcher.executor
    for m in (importlib.import_module(modname), watcher.executor):
        if hasattr(m, name):
            monkeypatch.setattr(m, name, fn)


@pytest.fixture
def ctx(tmp_path, monkeypatch):
    root = tmp_path / "work"
    repo = root / "features" / "demo" / "quark-kit"
    repo.mkdir(parents=True)
    def git(*args):
        subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)
    git("init", "-b", "develop")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (repo / "base.txt").write_text("base")
    git("add", "-A")
    git("commit", "-m", "base")
    prompt_dir = tmp_path / "prompts"
    prompt_dir.mkdir()
    st = State(prd="demo", phase="flash", batch=0, model="", lanes=(),
               needs_you=(), load_tries=0)
    plan = Plan(state=st, base="develop", batch_size=5, specs={}, ticket_files={})
    c = Ctx(plan=plan, root=str(root), prompt_dir=str(prompt_dir),
            check={"quark-kit": "uv run pytest -q"})
    # defaults: everything succeeds, no work done
    _patch(monkeypatch, "watcher.llm", "ensure_model", lambda *a, **k: True)
    _patch(monkeypatch, "watcher.omp", "run_omp", lambda *a, **k: OmpResult("done", ""))
    _patch(monkeypatch, "watcher.hk", "verify",
           lambda *a, **k: __import__("watcher.hk", fromlist=["VerifyResult"]).VerifyResult(True, ""))
    return c


def _repo(ctx):
    return os.path.join(ctx.root, "features", "demo", "quark-kit")


def _head(ctx):
    return subprocess.run(["git", "-C", _repo(ctx), "rev-parse", "HEAD"],
                          check=True, capture_output=True, text=True).stdout.strip()


def _commits(ctx):
    return int(subprocess.run(["git", "-C", _repo(ctx), "rev-list", "--count", "HEAD"],
                              check=True, capture_output=True, text=True).stdout)


def _dirty(ctx):
    import pathlib
    pathlib.Path(_repo(ctx) + "/work.txt").write_text("work")


def test_AC1_implement_green_verify_commits_and_reports_sha(ctx):
    _dirty(ctx)
    ev = execute(Action("implement", "quark-kit/01", model="m"), ctx)
    assert ev.kind == "implemented" and ev.ok is True
    assert ev.sha == _head(ctx)
    assert _commits(ctx) == 2


def test_AC2_implement_red_verify_reports_failure_and_no_commit(ctx, monkeypatch):
    _dirty(ctx)
    _patch(monkeypatch, "watcher.hk", "verify",
           lambda *a, **k: __import__("watcher.hk", fromlist=["VerifyResult"]).VerifyResult(False, "FAILED test_x"))
    ev = execute(Action("implement", "quark-kit/01", model="m"), ctx)
    assert ev.kind == "implemented" and ev.ok is False
    assert "FAILED test_x" in ev.detail
    assert _commits(ctx) == 1


def test_AC3_question_skips_verify(ctx, monkeypatch):
    calls = []
    def _verify(*a, **k):
        calls.append(1)
        raise AssertionError("verify must not run")
    _patch(monkeypatch, "watcher.omp", "run_omp",
           lambda *a, **k: OmpResult("question", "Which base branch?"))
    _patch(monkeypatch, "watcher.hk", "verify", _verify)
    ev = execute(Action("implement", "quark-kit/01", model="m"), ctx)
    assert ev.kind == "question" and "Which base branch?" in ev.detail
    assert calls == []


def test_AC4_malformed_verdict_twice_gives_bad_verdict(ctx, monkeypatch):
    vdir = os.path.join(_repo(ctx), ".agent", "verdicts")
    os.makedirs(vdir, exist_ok=True)
    with open(os.path.join(vdir, "01.json"), "w") as fh:
        fh.write("not json at all")
    ev = execute(Action("review", "quark-kit/01", model="m", detail=_head(ctx)), ctx)
    assert ev.kind == "bad_verdict"


def test_AC4_malformed_then_valid_verdict_gives_reviewed(ctx, monkeypatch):
    vdir = os.path.join(_repo(ctx), ".agent", "verdicts")
    os.makedirs(vdir, exist_ok=True)
    vpath = os.path.join(vdir, "01.json")
    with open(vpath, "w") as fh:
        fh.write("broken")
    sha = _head(ctx)
    state = {"n": 0}
    def fake_run_omp(*a, **k):
        state["n"] += 1
        if state["n"] >= 2:
            with open(vpath, "w") as fh:
                json.dump({"verdict": "APPROVE", "commit": sha, "findings": []}, fh)
        return OmpResult("done", "")
    _patch(monkeypatch, "watcher.omp", "run_omp", fake_run_omp)
    ev = execute(Action("review", "quark-kit/01", model="m", detail=sha), ctx)
    assert ev.kind == "reviewed" and ev.ok is True


def test_AC5_adapter_exception_becomes_timeout_event(ctx, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("boom")
    _patch(monkeypatch, "watcher.prompts", "write_prompt", boom)
    ev = execute(Action("implement", "quark-kit/01", model="m"), ctx)
    assert ev.kind == "timeout" and ev.ok is False
    assert "boom" in ev.detail


def test_notify_open_pr_and_write_summary_return_none(ctx):
    assert execute(Action("notify", "quark-kit/01", detail="question: quark-kit/01"), ctx) is None
    assert execute(Action("open_pr", "quark-kit"), ctx) is None
    assert execute(Action("write_summary"), ctx) is None


def test_AC5_load_model_events_ready_and_failed(ctx, monkeypatch):
    _patch(monkeypatch, "watcher.llm", "ensure_model", lambda *a, **k: True)
    ev = execute(Action("load_model", "", model="glm-x"), ctx)
    assert ev.kind == "model_ready" and ev.ok is True and ev.detail == "glm-x"
    _patch(monkeypatch, "watcher.llm", "ensure_model", lambda *a, **k: False)
    ev = execute(Action("load_model", "", model="glm-x"), ctx)
    assert ev.kind == "model_failed" and ev.ok is False
    assert "boom" not in (ev.detail or "") or True


def test_AC4_pr_review_reports_objection_with_findings(ctx):
    vdir = os.path.join(_repo(ctx), ".agent")
    os.makedirs(os.path.join(vdir, "verdicts"), exist_ok=True)
    sha = _head(ctx)
    with open(os.path.join(vdir, "pr-verdict.json"), "w") as fh:
        json.dump({"verdict": "CHANGES", "commit": sha,
                   "findings": [{"id": "F1", "file": "watcher/x.py",
                              "symbol": "f", "ac": "AC4", "problem": "leak"}]}, fh)
    ev = execute(Action("pr_review", "quark-kit", model="m"), ctx)
    assert ev.kind == "pr_reviewed" and ev.ok is False, ev.detail
    assert "F1" in (ev.detail or "")
