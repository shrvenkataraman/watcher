"""Ticket 10: PR-phase dispatch functions live in watcher/core_pr.py."""
import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

import watcher.core
from tests.ref.model import PHASE_MODEL, ref_step
from watcher.types import Event, Lane, State, TicketState, to_json

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("_dispatch_pr", "_open_ticket_work", "_back_to_work", "_pr_phase_end")


def _defs(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _j(obj):
    return json.loads(json.dumps(to_json(obj) if hasattr(obj, "__dataclass_fields__") else obj))


def _t(key, status, deps=()):
    return TicketState(key, 0, depends_on=deps, status=status)


def _lane(repo, statuses, pr_status="none", pr_tries=1, busy=False):
    return Lane(repo, tuple(_t(f"{repo}{i}", s) for i, s in enumerate(statuses)),
                pr_status, pr_tries, busy)


def _state(*lanes):
    return State(prd="demo", phase="pr", batch=0, model=PHASE_MODEL["pr"],
                 lanes=tuple(lanes), needs_you=(), load_tries=0)


@pytest.mark.parametrize("name", NAMES)
def test_AC2_function_moved_to_core_pr(name):
    # AC2
    import watcher.core_pr as core_pr
    assert name in _defs(ROOT / "watcher" / "core_pr.py")
    assert name not in _defs(ROOT / "watcher" / "core.py")
    assert getattr(watcher.core, name) is getattr(core_pr, name)


def test_AC3_import_core_in_fresh_interpreter():
    # AC3
    r = subprocess.run([sys.executable, "-c", "import watcher.core"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


SCENARIOS = {
    "dispatch_idle_finished": [_lane("a", ["approved"])],
    "dispatch_two_lanes": [_lane("a", ["approved"]), _lane("b", ["skipped"])],
    "skip_busy_lane": [_lane("a", ["approved"], busy=True)],
    "skip_unfinished_lane": [_lane("a", ["approved"], "ok"), _lane("b", ["running"])],
    "back_to_flash_ready_ticket": [_lane("a", ["approved"], "ok"), _lane("b", ["pending"])],
    "back_to_flash_changes": [_lane("a", ["approved"], "ok"), _lane("b", ["changes"])],
    "back_to_review_implemented": [_lane("a", ["approved"], "ok"), _lane("b", ["implemented"])],
    "back_to_review_fixed": [_lane("a", ["approved"], "ok"), _lane("b", ["fixed"])],
    "objected_goes_to_flash": [_lane("a", ["approved"], "objected:bad")],
    "all_done_summary": [_lane("a", ["approved"], "ok"), _lane("b", ["skipped"], "ok")],
    "parked_waits": [_lane("a", ["approved"], "ok"), _lane("b", ["needs_you"])],
    "parked_with_objection_ends": [_lane("a", ["approved"], "objected:x"),
                                   _lane("b", ["needs_you"])],
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_AC1_dispatch_pr_matches_reference(name):
    # AC1: a start event in the pr phase runs _dispatch_pr and its helpers.
    s = _state(*SCENARIOS[name])
    ev = Event("start", "")
    new, acts = watcher.core.step(s, ev)
    ref_new, ref_acts = ref_step(copy.deepcopy(_j(s)), _j(ev))
    assert _j(new) == ref_new
    assert [_j(a) for a in acts] == ref_acts


@pytest.mark.parametrize("name", ["dispatch_idle_finished", "back_to_flash_ready_ticket",
                                  "objected_goes_to_flash", "all_done_summary"])
def test_AC1_pr_phase_end_after_event_matches_reference(name):
    # AC1: pr_reviewed events close the round through _pr_phase_end.
    lanes = [Lane(l.repo, l.tickets, "running" if l.repo == "a" else l.pr_status,
                  l.pr_tries, l.repo == "a") for l in SCENARIOS[name]]
    s = _state(*lanes)
    ev = Event("pr_reviewed", "a", True)
    new, acts = watcher.core.step(s, ev)
    ref_new, ref_acts = ref_step(copy.deepcopy(_j(s)), _j(ev))
    assert _j(new) == ref_new
    assert [_j(a) for a in acts] == ref_acts
