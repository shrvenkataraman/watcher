"""run/tick read the config and pass adapters and models (watcher ticket 07)."""
import json
import os
import subprocess
import sys
import tempfile
from dataclasses import replace

from hypothesis import given, settings
from hypothesis import strategies as st

import watcher.cli as climod
import watcher.executor as execmod
import watcher.loop as loopmod
import watcher.report as repmod
from watcher.config import Config
from watcher.store import load, save
from watcher.types import Action, Event

FAKE = "tests.fakes.plugin:"
FLASH = "custom-flash-model"


def _cfg(models=None):
    return Config(models=models if models is not None else {"flash": FLASH, "review": "custom-review", "pr": "custom-pr"},
                  agent=FAKE + "FakeAgent", gate=FAKE + "FakeGate",
                  model_server=FAKE + "FakeServer", notifier=FAKE + "FakeNotifier")


def _inbox(base):
    inbox = os.path.join(base, "inbox")
    os.makedirs(os.path.join(inbox, "tickets", "demo"))
    with open(os.path.join(inbox, "spec.md"), "w") as f:
        f.write("# spec\n")
    with open(os.path.join(inbox, "manifest.json"), "w") as f:
        json.dump({"prd": "prd1", "base": "develop", "repos": {"demo": {"spec": "spec.md"}}}, f)
    with open(os.path.join(inbox, "tickets", "demo", "01-t.md"), "w") as f:
        f.write("# 01: t\nEdit: a.py\nTest: tests/t.py\nCheck: true\n")
    return inbox


def _capture(monkeypatch):
    loads = []

    def fake_execute(action, ctx):
        if action.kind == "load_model":
            loads.append(action.model)
            return Event("model_ready", detail=action.model)
        return None

    monkeypatch.setattr(execmod, "execute", fake_execute)
    monkeypatch.setattr(loopmod.executor, "execute", fake_execute)
    return loads


def _run_tick(base, cfg):
    return loopmod.tick("prd1", _inbox(base), os.path.join(base, "work"),
                        state_root=os.path.join(base, "state"), cfg=cfg)


def test_AC1_custom_models_saved_and_first_load_uses_flash(tmp_path, monkeypatch):
    loops = _capture(monkeypatch)
    cfg = _cfg()
    _run_tick(str(tmp_path), cfg)
    state = load("prd1", root=str(tmp_path / "state"))
    assert state.models == tuple(sorted(cfg.models.items()))
    assert loops[0] == FLASH


def test_AC1_fake_gate_sets_up_the_lane(tmp_path, monkeypatch):
    _capture(monkeypatch)
    seen = []
    from tests.fakes.plugin import FakeGate
    orig = FakeGate.ensure_lane

    def spy(self, *a, **k):
        seen.append(a)
        return orig(self, *a, **k)

    monkeypatch.setattr(FakeGate, "ensure_lane", spy)
    _run_tick(str(tmp_path), _cfg())
    assert seen and seen[0][0] == "prd1" and seen[0][1] == "demo" and seen[0][3] == "true"


@settings(max_examples=15, deadline=None)
@given(st.dictionaries(st.text("abcdef", min_size=1, max_size=4),
                       st.text("xyz-", min_size=1, max_size=6), max_size=4))
def test_AC1_property_new_run_models_equal_sorted_items(models):
    with tempfile.TemporaryDirectory() as base:
        orig = loopmod.executor.execute
        loopmod.executor.execute = lambda action, ctx: None
        try:
            _run_tick(base, _cfg(models))
        finally:
            loopmod.executor.execute = orig
        assert load("prd1", root=os.path.join(base, "state")).models == tuple(sorted(models.items()))


def test_AC1_property_resume_keeps_saved_models(tmp_path, monkeypatch):
    _capture(monkeypatch)
    base = str(tmp_path)
    _run_tick(base, _cfg({"flash": "first"}))
    loopmod.RECONCILED.clear()
    loopmod.tick("prd1", os.path.join(base, "inbox"), os.path.join(base, "work"),
                 state_root=os.path.join(base, "state"), cfg=_cfg({"flash": "second"}))
    assert load("prd1", root=os.path.join(base, "state")).models == (("flash", "first"),)


def test_AC2_notify_action_reaches_fake_notifier(tmp_path, monkeypatch):
    _capture(monkeypatch)
    legacy = []
    monkeypatch.setattr(repmod, "notify", lambda *a, **k: legacy.append(a))
    from tests.fakes.plugin import FakeNotifier
    got = []
    monkeypatch.setattr(FakeNotifier, "notify", lambda self, t, b, **k: got.append((t, b)))
    real = loopmod.core.step

    def step(state, event):
        state, actions = real(state, event)
        if event.kind == "start":
            actions = (*actions, Action("notify", key="K", detail="D"))
        return state, actions

    monkeypatch.setattr(loopmod.core, "step", step)
    _run_tick(str(tmp_path), _cfg())
    assert ("K", "D") in got
    assert legacy == []


def test_AC2_open_pr_failure_notifies_through_adapter(tmp_path, monkeypatch):
    from tests.fakes.plugin import FakeNotifier
    got = []
    monkeypatch.setattr(FakeNotifier, "notify", lambda self, t, b, **k: got.append((t, b)))
    legacy = []
    monkeypatch.setattr(repmod, "notify", lambda *a, **k: legacy.append(a))

    def boom(*a, **k):
        raise RuntimeError("nope")

    monkeypatch.setattr(loopmod.gh, "open_pr", boom)
    base = str(tmp_path)
    _capture(monkeypatch)
    # drive a tick so a plan and ctx exist, then run open_pr by hand
    _run_tick(base, _cfg())
    from watcher import inbox as inboxmod
    from watcher.plugins import build_adapters
    plan = inboxmod.load_inbox(os.path.join(base, "inbox"))
    ctx = execmod.Ctx(plan=plan, root=os.path.join(base, "work"), check={}, prompt_dir=base,
                      adapters=build_adapters(_cfg()))
    sroot = os.path.join(base, "state")
    os.makedirs(os.path.join(sroot, "watcher", "prd1"), exist_ok=True)
    try:
        loopmod._act(Action("open_pr", key="demo"), plan.state, plan, ctx, "prd1", sroot,
                     lambda: "now")
    except TypeError:
        raise
    assert any("open_pr failed" in b for _, b in got)
    assert legacy == []


def test_AC3_cli_tick_loads_the_named_config(tmp_path, monkeypatch):
    seen, ticks = [], []
    cfg = _cfg()
    monkeypatch.setattr(climod, "load_config", lambda path=None: seen.append(path) or cfg)
    monkeypatch.setattr(loopmod, "tick", lambda *a, **k: ticks.append(k) or False)
    rc = climod.main(["tick", "--config", "F.toml", "--prd", "P", "--inbox", "I"])
    assert rc == 0
    assert seen == ["F.toml"]
    assert ticks[0]["cfg"] is cfg


def test_AC3_cli_run_passes_cfg_to_run(monkeypatch):
    seen, runs = [], []
    cfg = _cfg()
    monkeypatch.setattr(climod, "load_config", lambda path=None: seen.append(path) or cfg)
    monkeypatch.setattr(loopmod, "run", lambda *a, **k: runs.append(k) or 0)
    assert climod.main(["run", "--config", "G.toml", "--prd", "P", "--inbox", "I"]) == 0
    assert seen == ["G.toml"] and runs[0]["cfg"] is cfg


def test_AC3_config_defaults_to_none(monkeypatch):
    seen = []
    monkeypatch.setattr(climod, "load_config", lambda path=None: seen.append(path) or _cfg())
    monkeypatch.setattr(loopmod, "tick", lambda *a, **k: False)
    climod.main(["tick", "--prd", "P", "--inbox", "I"])
    assert seen == [None]


def test_AC3_run_passes_cfg_through_to_tick(tmp_path, monkeypatch):
    got = []
    monkeypatch.setattr(loopmod, "tick", lambda *a, **k: got.append(k.get("cfg")) or False)
    cfg = _cfg()
    loopmod.run("prd1", "I", str(tmp_path), state_root=str(tmp_path / "s"), cfg=cfg)
    assert got == [cfg]


def test_AC4_existing_loop_tests_pass_unchanged():
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    out = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_loop.py"],
                         cwd=here, capture_output=True, text=True)
    assert out.returncode == 0, out.stdout[-800:]
