"""Core PR phase with one retry (watcher ticket 09)."""
import copy
import json
import random

from tests.ref.model import PHASE_MODEL, ref_step
from watcher.core import step
from watcher.types import Event, Lane, State, TicketState, to_json

FLASH = PHASE_MODEL["flash"]
GLM = PHASE_MODEL["pr"]


def _norm(obj) -> dict:
    return json.loads(json.dumps(to_json(obj) if hasattr(obj, "__dataclass_fields__") else obj))


def _actions_json(actions) -> list:
    return [json.loads(json.dumps(to_json(a))) for a in actions]


def _lane(repo, tickets, pr_status="none", pr_tries=0, busy=False):
    return Lane(repo, tuple(TicketState(key, 0, status=st) for key, st in tickets),
                pr_status, pr_tries, busy)


def _pr_state(lanes, phase="pr", model=""):
    return State(prd="demo", phase=phase, batch=0, model=model, lanes=tuple(lanes),
                 needs_you=(), load_tries=0)


def _both(s: State, ev: Event):
    """core.step and the reference must agree on state and actions."""
    new, actions = step(s, ev)
    ref_new, ref_acts = ref_step(copy.deepcopy(_norm(s)), _norm(ev))
    assert _norm(new) == ref_new, (ev, _norm(new), ref_new)
    assert _actions_json(actions) == ref_acts, (ev, _actions_json(actions), ref_acts)
    return new, actions


def _kinds(actions):
    return [a.kind for a in actions]


def _finished_pr():
    return _pr_state([_lane("a", [("a/01", "approved")]),
                      _lane("b", [("b/01", "approved")])])


def test_AC1_each_finished_lane_gets_exactly_one_pr_review():
    s = _finished_pr()
    new, acts = _both(s, Event("model_ready", detail=GLM))
    assert sorted((a.kind, a.key) for a in acts) == [("pr_review", "a"), ("pr_review", "b")]
    assert all(l.pr_status == "running" for l in new.lanes)


def test_AC2_approval_emits_open_pr_for_that_repo():
    s = _finished_pr()
    s, _ = _both(s, Event("model_ready", detail=GLM))
    new, acts = _both(s, Event("pr_reviewed", key="a", ok=True))
    assert _kinds(acts) == ["open_pr"]
    assert new.lanes[0].pr_status == "approved"


def _round_trip_after_objection():
    """One lane: review, objection, flash pr_fix, back to pr, second review."""
    s = _pr_state([_lane("a", [("a/01", "approved")])])
    s, acts = _both(s, Event("model_ready", detail=GLM))
    assert _kinds(acts) == ["pr_review"]
    s, acts = _both(s, Event("pr_reviewed", key="a", ok=False, detail="add tests"))
    assert _kinds(acts) == ["load_model"] and acts[0].model == FLASH
    assert s.lanes[0].pr_status == "objected:add tests" and s.lanes[0].pr_tries == 1
    s, acts = _both(s, Event("model_ready", detail=FLASH))
    assert _kinds(acts) == ["pr_fix"] and acts[0].detail == "add tests"
    s, acts = _both(s, Event("pr_fixed", key="a", ok=True))
    assert _kinds(acts) == ["load_model"] and acts[0].model == GLM
    s, acts = _both(s, Event("model_ready", detail=GLM))
    assert _kinds(acts) == ["pr_review"]  # second review, same lane
    return s


def test_AC3_objection_leads_to_pr_fix_then_second_review():
    s = _round_trip_after_objection()
    assert s.lanes[0].pr_tries == 1


def test_AC4_second_objection_parks_the_repo():
    s = _round_trip_after_objection()
    new, acts = _both(s, Event("pr_reviewed", key="a", ok=False, detail="still bad"))
    assert new.lanes[0].pr_status == "needs_you"
    assert ("a", "pr_objected_twice") in [(n.key, n.reason) for n in new.needs_you]
    assert _kinds(acts) == ["notify", "write_summary"]  # AC5: round ends, done


def test_AC5_all_resolved_ends_done_with_one_summary():
    s = _finished_pr()
    s, _ = _both(s, Event("model_ready", detail=GLM))
    s, acts = _both(s, Event("pr_reviewed", key="a", ok=True))
    assert _kinds(acts) == ["open_pr"]
    s, acts = _both(s, Event("pr_reviewed", key="b", ok=True))
    assert _kinds(acts) == ["open_pr", "write_summary"]
    assert s.phase == "done"


def test_pending_lane_never_gets_pr_review():
    s = _pr_state([_lane("a", [("a/01", "approved")]),
                   _lane("b", [("b/01", "approved"), ("b/02", "pending")])])
    _, acts = _both(s, Event("model_ready", detail=GLM))
    assert _kinds(acts) == ["pr_review"] and acts[0].key == "a"


def test_pr_tries_never_exceeds_one_random_walk():
    rng = random.Random(20261114)
    s = _pr_state([_lane("a", [("a/01", "approved")])])
    for _ in range(40):
        if s.phase == "done":
            break
        if s.model != PHASE_MODEL[s.phase]:
            s, _ = _both(s, Event("model_ready", detail=PHASE_MODEL[s.phase]))
            continue
        roll = rng.random()
        if roll < 0.4:
            s, _ = _both(s, Event("pr_reviewed", key="a", ok=rng.random() < 0.5,
                                  detail="obj text"))
        else:
            s, _ = _both(s, Event("pr_fixed", key="a", ok=rng.random() < 0.5,
                                  detail="obj text"))
        assert all(l.pr_tries <= 1 for l in s.lanes)
