"""Ticket 11: review-phase dispatch functions live in watcher/core_review.py."""
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
NAMES = ("_dispatch_review", "_next_phase")


def _defs(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _j(obj):
    return json.loads(json.dumps(to_json(obj) if hasattr(obj, "__dataclass_fields__") else obj))


def _t(key, status, batch=0, deps=()):
    return TicketState(key, batch, depends_on=deps, status=status)


def _lane(repo, specs, busy=False):
    ts = tuple(_t(f"{repo}{i}", *((s,) if isinstance(s, str) else s))
               for i, s in enumerate(specs))
    return Lane(repo, ts, "none", 0, busy)


def _state(*lanes, batch=0):
    return State(prd="demo", phase="review", batch=batch, model=PHASE_MODEL["review"],
                 lanes=tuple(lanes), needs_you=(), load_tries=0)


@pytest.mark.parametrize("name", NAMES)
def test_AC2_function_moved_to_core_review(name):
    # AC2
    import watcher.core_review as core_review
    assert name in _defs(ROOT / "watcher" / "core_review.py")
    assert name not in _defs(ROOT / "watcher" / "core.py")
    assert getattr(watcher.core, name) is getattr(core_review, name)


def test_AC3_import_core_in_fresh_interpreter():
    # AC3
    r = subprocess.run([sys.executable, "-c", "import watcher.core"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_AC1_existing_core_tests_still_importable():
    # AC1: the frozen core suites run unchanged against the re-exported names.
    import watcher.core_review  # noqa: F401
    for n in NAMES:
        assert callable(getattr(watcher.core, n))
    assert callable(watcher.core.step)


SCENARIOS = {
    "implemented_dispatched": [_lane("a", ["implemented"])],
    "fixed_dispatched_detail": [_lane("a", ["fixed"])],
    "two_lanes": [_lane("a", ["implemented"]), _lane("b", ["fixed", "implemented"])],
    "busy_lane_skipped": [_lane("a", ["implemented"], busy=True)],
    "busy_lane_with_idle": [_lane("a", ["implemented"], busy=True), _lane("b", ["implemented"])],
    "first_of_many": [_lane("a", ["approved", "implemented", "fixed"])],
    "to_flash_changes": [_lane("a", ["changes", "approved"])],
    "to_flash_next_batch": [_lane("a", ["approved", ("pending", 1)])],
    "to_flash_ready_now": [_lane("a", ["approved", "pending"])],
    "to_flash_same_batch_open": [_lane("a", ["pending", ("approved", 0)], busy=False)],
    "to_flash_batch_bumps": [_lane("a", ["approved", ("pending", 1)])],
    "to_pr_all_done": [_lane("a", ["approved"]), _lane("b", ["skipped"])],
    "to_pr_blocked_pending": [_lane("a", ["needs_you", ("pending", 0, ("a0",))])],
    "dep_not_ready": [_lane("a", ["approved", ("pending", 0, ("zz",))])],
}


@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_AC1_dispatch_review_matches_reference(name):
    # AC1: start in review phase runs _dispatch_review and _next_phase.
    s = _state(*SCENARIOS[name])
    ev = Event("start", "")
    new, acts = watcher.core.step(s, ev)
    ref_new, ref_acts = ref_step(copy.deepcopy(_j(s)), _j(ev))
    assert _j(new) == ref_new
    assert [_j(a) for a in acts] == ref_acts


@pytest.mark.parametrize("ok", [True, False])
def test_AC1_reviewed_event_reaches_next_phase_matches_reference(ok):
    # AC1: a reviewed event re-dispatches and may leave the review phase.
    lane = Lane("a", (_t("a0", "running"),), "none", 0, True)
    s = _state(lane)
    ev = Event("reviewed", "a0", ok, "bad")
    new, acts = watcher.core.step(s, ev)
    ref_new, ref_acts = ref_step(copy.deepcopy(_j(s)), _j(ev))
    assert _j(new) == ref_new
    assert [_j(a) for a in acts] == ref_acts
