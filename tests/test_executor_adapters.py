"""Executor calls adapters from Ctx, with no monkeypatching (ticket 05)."""
import pathlib
import subprocess
import sys

import pytest

import watcher.executor as exmod
from watcher.adapters import default_adapters
from watcher.executor import Ctx, execute
from watcher.inbox import Plan
from watcher.ports import Adapters, AgentResult, GateResult
from watcher.types import Action, State

REPO_REL = ("features", "demo", "quark-kit")


class FakeAgent:
    def __init__(self, repo, outcome="done", edit=True):
        self.repo, self.outcome, self.edit, self.calls = repo, outcome, edit, []

    def run(self, role, model, worktree, prompt_file, task):
        self.calls.append((role, model, worktree))
        if self.edit:
            pathlib.Path(worktree, "work.txt").write_text("work")
        return AgentResult(self.outcome, "")


class FakeGate:
    def __init__(self, repo, verify=GateResult(True, ""), review=GateResult(True, "")):
        self.repo, self._verify, self._review = repo, verify, review
        self.calls = []

    def lane_worktree(self, root, prd, repo):
        self.calls.append(("lane_worktree", root, prd, repo))
        return self.repo

    def ensure_lane(self, prd, repo, base, check, root):
        return self.repo

    def verify(self, worktree):
        self.calls.append(("verify", worktree))
        return self._verify

    def review(self, worktree):
        self.calls.append(("review", worktree))
        return self._review


class FakeServer:
    def __init__(self, ready):
        self.ready, self.calls = ready, []

    def ensure_model(self, name):
        self.calls.append(name)
        return self.ready


class FakeNotifier:
    def notify(self, title, body):
        pass


def _make(tmp_path, gate=None, agent=None, server=None):
    root = tmp_path / "work"
    repo = root.joinpath(*REPO_REL)
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
    adapters = Adapters(agent or FakeAgent(str(repo)), gate or FakeGate(str(repo)),
                        server or FakeServer(True), FakeNotifier())
    ctx = Ctx(plan=plan, root=str(root), prompt_dir=str(prompt_dir),
              check={"quark-kit": "uv run pytest -q"}, adapters=adapters)
    return ctx, str(repo)


def _head(repo):
    return subprocess.run(["git", "-C", repo, "rev-parse", "HEAD"], check=True,
                          capture_output=True, text=True).stdout.strip()


def test_AC1_implement_end_to_end_with_fake_adapters(tmp_path, monkeypatch):
    monkeypatch.setattr(exmod, "LOAD_RETRY_WAIT", 0)
    ctx, repo = _make(tmp_path)
    before = _head(repo)
    ev = execute(Action("implement", "quark-kit/01", model="m"), ctx)
    assert ev.kind == "implemented" and ev.ok is True
    assert ev.sha and ev.sha != before and ev.sha == _head(repo)
    assert ctx.adapters.agent.calls == [("implement", "m", repo)]
    assert ("verify", repo) in ctx.adapters.gate.calls
    assert ("review", repo) in ctx.adapters.gate.calls
    assert ("lane_worktree", ctx.root, "demo", "quark-kit") in ctx.adapters.gate.calls


def test_AC1_ctx_defaults_to_default_adapters(tmp_path):
    ctx, _ = _make(tmp_path)
    plain = Ctx(plan=ctx.plan, root=ctx.root, prompt_dir=ctx.prompt_dir, check={})
    assert type(plain.adapters.agent) is type(default_adapters().agent)
    assert type(plain.adapters.gate) is type(default_adapters().gate)


def test_AC1_agent_error_reports_omp_error(tmp_path):
    ctx, repo = _make(tmp_path, agent=FakeAgent("", outcome="error", edit=False))
    ev = execute(Action("implement", "quark-kit/01", model="m"), ctx)
    assert ev.kind == "implemented" and ev.ok is False
    assert ev.detail.startswith("omp error")


def test_AC2_red_verify_gives_not_ok_with_tail(tmp_path):
    gate = FakeGate("", verify=GateResult(False, "red"))
    ctx, repo = _make(tmp_path)
    gate.repo = repo
    ctx = Ctx(plan=ctx.plan, root=ctx.root, prompt_dir=ctx.prompt_dir, check=ctx.check,
              adapters=Adapters(ctx.adapters.agent, gate, ctx.adapters.model_server,
                                FakeNotifier()))
    ev = execute(Action("implement", "quark-kit/01", model="m"), ctx)
    assert ev.kind == "implemented" and ev.ok is False
    assert "red" in ev.detail
    assert not any(c[0] == "review" for c in gate.calls)


def test_AC2_rejected_review_gives_not_ok(tmp_path):
    ctx, repo = _make(tmp_path)
    gate = FakeGate(repo, review=GateResult(False, "nope"))
    ctx = Ctx(plan=ctx.plan, root=ctx.root, prompt_dir=ctx.prompt_dir, check=ctx.check,
              adapters=Adapters(ctx.adapters.agent, gate, ctx.adapters.model_server,
                                FakeNotifier()))
    ev = execute(Action("implement", "quark-kit/01", model="m"), ctx)
    assert ev.ok is False and ev.detail == "hk review rejected: nope"


@pytest.mark.parametrize("ready,kind", [(False, "model_failed"), (True, "model_ready")])
def test_AC3_load_model_uses_fake_server(tmp_path, monkeypatch, ready, kind):
    monkeypatch.setattr(exmod, "LOAD_RETRY_WAIT", 0)
    server = FakeServer(ready)
    ctx, _ = _make(tmp_path, server=server)
    ev = execute(Action("load_model", "", model="big"), ctx)
    assert ev.kind == kind and ev.ok is ready and ev.detail == "big"
    assert server.calls == ["big"]


def test_AC4_existing_executor_tests_pass_unchanged():
    root = pathlib.Path(__file__).resolve().parent.parent
    r = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_executor.py"],
                       cwd=root, capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-2000:]
