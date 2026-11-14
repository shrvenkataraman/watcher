"""Run loop: tick, single-instance lock, crash resume, queue drain (watcher ticket 22)."""
import copy
import fcntl
import json
import os
import subprocess
from pathlib import Path

import pytest

import watcher.executor as execmod
import watcher.gh as ghmod
import watcher.report as repmod
from tests.ref.model import ref_step
from watcher.loop import run, tick
from watcher.types import Event, State, to_json

REPO = "demo"


def _norm(obj) -> dict:
    return json.loads(json.dumps(to_json(obj) if hasattr(obj, "__dataclass_fields__") else obj))


def _patch(monkeypatch, modname, name, fn):
    import watcher.loop
    mod = __import__(modname, fromlist=["x"])
    for target in (mod, watcher.loop):
        if hasattr(target, name):
            monkeypatch.setattr(target, name, fn)


@pytest.fixture
def world(tmp_path, monkeypatch):
    root = tmp_path / "work"
    wt = root / "features" / "demo" / REPO
    wt.mkdir(parents=True)
    def git(*args):
        subprocess.run(["git", "-C", str(wt), *args], check=True, capture_output=True)
    (wt / ".agent").mkdir()
    (wt / ".agent" / "contract.json").write_text("{}")
    git("init", "-b", "develop")
    git("config", "user.email", "t@t")
    git("config", "user.name", "t")
    (wt / "base.txt").write_text("base")
    git("add", "-A")
    git("commit", "-m", "base")
    inbox = tmp_path / "inbox"
    inbox.mkdir()
    (inbox / "spec.md").write_text("# demo spec\n")
    (inbox / "manifest.json").write_text(json.dumps(
        {"prd": "demo", "base": "develop", "repos": {REPO: {"spec": "spec.md"}}}))
    for nn in ("01", "02", "03"):
        d = inbox / "tickets" / REPO
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{nn}-ticket.md").write_text(
            f"# {nn}: t\nEdit: watcher/x.py\nTest: tests/t.py\nCheck: true\n")
    state_root = str(tmp_path / "state")
    calls = {"impl": [], "open_pr": [], "summary": [], "notify": []}

    def fake_execute(action, ctx):
        if action.kind == "load_model":
            return Event("model_ready", detail=action.model)
        if action.kind in ("implement", "fix"):
            calls["impl"].append(action.key)
            sha = f"sha-{action.key}-{len(calls['impl'])}"
            (wt / f"{action.key.replace('/', '_')}.py").write_text("work")
            git("add", "-A")
            git("commit", "-m", f"feat: {action.key}\n\nWatcher-Ticket: {action.key}")
            kind = "implemented" if action.kind == "implement" else "fixed"
            return Event(kind, key=action.key, ok=True, sha=sha)
        if action.kind == "review":
            return Event("reviewed", key=action.key, ok=True, detail="[]")
        if action.kind == "pr_review":
            return Event("pr_reviewed", key=action.key, ok=True, detail="[]")
        if action.kind == "pr_fix":
            return Event("pr_fixed", key=action.key, ok=True)
        return None

    _patch(monkeypatch, "watcher.executor", "execute", fake_execute)
    _patch(monkeypatch, "watcher.gh", "open_pr",
           lambda *a, **k: calls["open_pr"].append(a) or "ok")
    _patch(monkeypatch, "watcher.report", "write_summary",
           lambda *a, **k: calls["summary"].append(1))
    _patch(monkeypatch, "watcher.report", "notify",
           lambda *a, **k: calls["notify"].append(a))
    return {"root": str(root), "inbox": str(inbox), "state_root": state_root,
            "wt": str(wt), "calls": calls, "git": git}


def _tick_until_done(w, limit=60):
    n = 0
    while tick("demo", w["inbox"], w["root"], state_root=w["state_root"]) and n < limit:
        n += 1
    assert n < limit, "tick never reached done"


def test_AC1_three_tickets_finish_with_one_open_pr(world):
    _tick_until_done(world)
    from watcher.store import load
    s = load("demo", root=world["state_root"])
    assert s.phase == "done"
    statuses = [t.status for lane in s.lanes for t in lane.tickets]
    assert statuses == ["approved"] * 3
    assert len(world["calls"]["open_pr"]) == 1
    assert world["calls"]["summary"]  # summary written at done
    # reference-model replay over the recorded event log yields the same final state
    from watcher.store import read_events
    ref = _norm(__import__("watcher.inbox", fromlist=["load_inbox"]).load_inbox(
        world["inbox"]).state)
    for ev in read_events("demo", root=world["state_root"]):
        ref, _ = ref_step(ref, _norm(ev))
    assert _norm(ref) == _norm(s)


def test_AC2_crash_after_commit_does_not_rerun(world, monkeypatch):
    w = world
    real_execute = execmod.execute

    class Boom(RuntimeError):
        pass

    n = {"impl": 0}

    def crashing(action, ctx):
        if action.kind == "implement":
            n["impl"] += 1
            if n["impl"] == 2:
                # commit the work, THEN crash: resume must find the commit
                (Path(w["wt"]) / f"{action.key.replace('/', '_')}.py").write_text("work")
                w["git"]("add", "-A")
                w["git"]("commit", "-m",
                         f"feat: {action.key}\n\nWatcher-Ticket: {action.key}")
                raise Boom(action.key)
        return real_execute(action, ctx)

    _patch(monkeypatch, "watcher.executor", "execute", crashing)
    with pytest.raises(Boom):
        while tick("demo", w["inbox"], w["root"], state_root=w["state_root"]):
            if n["impl"] >= 2:
                break
    _patch(monkeypatch, "watcher.executor", "execute", real_execute)
    _tick_until_done(w)
    # ticket 02 crashed WITH its commit: resume skips it, it is never re-implemented
    assert w["calls"]["impl"] == ["demo/01", "demo/03"]
    commits = subprocess.run(["git", "-C", w["wt"], "log", "--format=%B"],
                             capture_output=True, text=True).stdout
    for key in ("demo/01", "demo/02", "demo/03"):
        assert commits.count(f"Watcher-Ticket: {key}") == 1


def test_AC3_locked_tick_does_nothing(world):
    sd = os.path.join(world["state_root"], "watcher", "demo")
    os.makedirs(sd, exist_ok=True)
    lock = open(os.path.join(sd, "run.lock"), "w")
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    assert tick("demo", world["inbox"], world["root"],
                state_root=world["state_root"]) is True
    assert world["calls"]["impl"] == []
    assert not os.path.exists(os.path.join(sd, "state.json"))


def test_AC4_queued_skip_applies_next_tick(world):
    from watcher.inbox import load_inbox
    from watcher.store import save
    from watcher.types import NeedsYou, TicketState
    from dataclasses import replace
    s = load_inbox(world["inbox"]).state
    lane = s.lanes[0]
    tickets = tuple(
        replace(t, status="needs_you") if t.key == "demo/02" else t
        for t in lane.tickets)
    s = replace(s, lanes=(replace(lane, tickets=tickets),),
                needs_you=(NeedsYou("demo/02", "question", "why"),))
    save(s, root=world["state_root"])
    sd = os.path.join(world["state_root"], "watcher", "demo")
    with open(os.path.join(sd, "queue.jsonl"), "w") as fh:
        fh.write(json.dumps({"kind": "skip", "key": "demo/02",
                             "ok": True, "sha": "", "detail": ""}) + "\n")
    tick("demo", world["inbox"], world["root"], state_root=world["state_root"])
    from watcher.store import load
    after = load("demo", root=world["state_root"])
    t = [t for lane in after.lanes for t in lane.tickets if t.key == "demo/02"][0]
    assert t.status == "skipped"
    assert [n.key for n in after.needs_you] == []


def test_run_returns_zero_when_done(world):
    _tick_until_done(world)
    assert run("demo", world["inbox"], world["root"],
               state_root=world["state_root"], sleep=lambda s: None) == 0


def test_review_action_carries_the_ticket_commit(monkeypatch):
    import watcher.loop as loopmod
    from watcher.types import Action, Lane, State, TicketState
    seen = []
    monkeypatch.setattr(loopmod.executor, "execute", lambda a, c: seen.append(a) or None)
    st = State(prd="p", phase="review", lanes=(Lane(repo="r", tickets=(
        TicketState(key="r/01", batch=0, status="running", sha="abc123"),)),))
    loopmod._act(Action("review", "r/01", model="m", detail="fixed"), st, None, None, "p", None, None)
    assert seen[0].detail == "abc123"


def test_second_run_for_same_prd_exits_3(tmp_path):
    import watcher.loop as loopmod
    from watcher import store
    parent = os.path.dirname(store.state_dir("p", str(tmp_path)))
    os.makedirs(parent, exist_ok=True)
    held = open(os.path.join(parent, "p.run.lock"), "a")
    fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
    try:
        assert loopmod.run("p", "unused", "unused", state_root=str(tmp_path)) == 3
    finally:
        held.close()


def test_open_pr_failure_notifies_instead_of_crashing(monkeypatch):
    import watcher.loop as lp
    from types import SimpleNamespace
    from watcher.types import Action
    seen = []
    monkeypatch.setattr(lp.gh, "open_pr", lambda *a: (_ for _ in ()).throw(RuntimeError("refused")))
    monkeypatch.setattr(lp.report, "notify", lambda k, d: seen.append(d))
    monkeypatch.setattr(lp.store, "state_dir", lambda *a: "/tmp")
    plan = SimpleNamespace(state=SimpleNamespace(prd="p"), specs={}, base="develop")
    ctx = SimpleNamespace(root="/tmp")
    assert lp._act(Action("open_pr", "r"), None, plan, ctx, "p", None, lambda: "") is None
    assert seen and "refused" in seen[0]
