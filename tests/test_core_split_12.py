"""Ticket 12: ticket status updates live in watcher/core_marks.py."""
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
NAMES = ("_mark_reviewed", "_mark_fixed", "_mark_implemented")


def _defs(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _j(obj):
    return json.loads(json.dumps(to_json(obj) if hasattr(obj, "__dataclass_fields__") else obj))


def _t(key, status, fix_rounds=0):
    return TicketState(key, 0, status=status, fix_rounds=fix_rounds)


def _lane(repo, specs, busy=True):
    ts = tuple(_t(f"{repo}{i}", *((s,) if isinstance(s, str) else s))
               for i, s in enumerate(specs))
    return Lane(repo, ts, "none", 0, busy)


def _state(phase, *lanes):
    return State(prd="demo", phase=phase, batch=0, model=PHASE_MODEL[phase],
                 lanes=tuple(lanes), needs_you=(), load_tries=0)


@pytest.mark.parametrize("name", NAMES)
def test_AC2_function_moved_to_core_marks(name):
    # AC2
    import watcher.core_marks as core_marks
    assert name in _defs(ROOT / "watcher" / "core_marks.py")
    assert name not in _defs(ROOT / "watcher" / "core.py")
    assert getattr(watcher.core, name) is getattr(core_marks, name)


def test_AC3_import_core_in_fresh_interpreter():
    # AC3
    r = subprocess.run([sys.executable, "-c", "import watcher.core"],
                       cwd=ROOT, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr


def test_AC1_existing_core_tests_still_importable():
    # AC1: the frozen core suites run unchanged against the re-exported names.
    import watcher.core_marks  # noqa: F401
    for n in NAMES:
        assert callable(getattr(watcher.core, n))
    assert callable(watcher.core.step)


def _check(s, ev):
    new, acts = watcher.core.step(s, ev)
    ref_new, ref_acts = ref_step(copy.deepcopy(_j(s)), _j(ev))
    assert _j(new) == ref_new
    assert [_j(a) for a in acts] == ref_acts


@pytest.mark.parametrize("phase", ["flash", "review"])
@pytest.mark.parametrize("kind", ["implemented", "fixed"])
@pytest.mark.parametrize("scenario", [
    [_lane("a", ["running"])],
    [_lane("a", ["running", "pending"])],
    [_lane("a", [("running", 1)]), _lane("b", ["running"])],
    [_lane("a", ["running"], busy=False)],
])
def test_AC1_implemented_fixed_match_reference(phase, kind, scenario):
    # AC1: _mark_implemented and _mark_fixed record sha, free the lane.
    s = _state(phase, *scenario)
    _check(s, Event(kind, "a0", True, "abc123"))


def test_AC1_mark_unknown_key_match_reference():
    # AC1: a key no lane carries leaves lanes unchanged.
    s = _state("flash", _lane("a", ["running"]))
    _check(s, Event("implemented", "zz", True, "abc"))
    _check(s, Event("fixed", "zz", True, "abc"))


@pytest.mark.parametrize("ok", [True, False])
@pytest.mark.parametrize("rounds", [0, 1])
def test_AC1_reviewed_matches_reference(ok, rounds):
    # AC1: _mark_reviewed approves, asks for changes, or parks after a spent fix round.
    s = _state("review", _lane("a", [("running", rounds)]))
    _check(s, Event("reviewed", "a0", ok, detail="bad"))


def test_AC1_reviewed_unknown_key_returns_empty():
    # AC1: _mark_reviewed returns None for an unknown key; step emits nothing.
    s = _state("review", _lane("a", ["running"]))
    new, acts = watcher.core.step(s, Event("reviewed", "zz", True))
    assert new == s and acts == ()
    _check(s, Event("reviewed", "zz", True))
