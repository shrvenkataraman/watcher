"""Ticket 09: PR event functions live in watcher/core_pr.py."""
import ast
import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

import watcher.core
from tests.ref.model import ref_step
from watcher.types import Event, Lane, State, TicketState, to_json

ROOT = Path(__file__).resolve().parent.parent
NAMES = ("_pr_reviewed", "_pr_fixed", "_parked_repo", "_notify_repo")


def _defs(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    return {n.name for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _j(obj):
    return json.loads(json.dumps(to_json(obj) if hasattr(obj, "__dataclass_fields__") else obj))


def _state(pr_status, pr_tries):
    lane = Lane("r", (TicketState("t", 0, status="done"),), pr_status, pr_tries, True)
    return State(prd="demo", phase="pr", batch=0, model="", lanes=(lane,),
                 needs_you=(), load_tries=0)


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


@pytest.mark.parametrize("pr_status,tries,ev", [
    ("running", 0, Event("pr_reviewed", "r", True)),
    ("running", 0, Event("pr_reviewed", "r", False, detail="bad")),
    ("running", 1, Event("pr_reviewed", "r", False, detail="bad")),
    ("fixing", 1, Event("pr_fixed", "r", True)),
    ("fixing", 1, Event("pr_fixed", "r", False, detail="bad")),
    ("none", 0, Event("pr_reviewed", "r", True)),
])
def test_AC1_pr_events_match_reference(pr_status, tries, ev):
    # AC1
    s = _state(pr_status, tries)
    new, acts = watcher.core.step(s, ev)
    ref_new, ref_acts = ref_step(copy.deepcopy(_j(s)), _j(ev))
    assert _j(new) == ref_new
    assert [_j(a) for a in acts] == ref_acts
