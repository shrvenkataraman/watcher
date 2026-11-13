"""Core frozen dataclasses and JSON round-trip helpers (watcher ticket 01)."""
import dataclasses
import json

import pytest
from hypothesis import given, settings
import hypothesis.strategies as st

from watcher.types import (
    PHASE_MODEL,
    TICKET_STATUSES,
    Action,
    Event,
    Lane,
    NeedsYou,
    State,
    TicketState,
    event_from_json,
    state_from_json,
    to_json,
)

KEYS = ("quark-kit/03", "qresearch/12", "ml_earningsq/07")

ticket_st = st.builds(
    TicketState,
    key=st.sampled_from(KEYS),
    batch=st.integers(0, 3),
    depends_on=st.lists(st.sampled_from(KEYS), max_size=3).map(tuple),
    status=st.sampled_from(TICKET_STATUSES),
    sha=st.from_regex(r"[0-9a-f]{0,8}", fullmatch=True),
    verify_fails=st.integers(0, 2),
    fix_rounds=st.integers(0, 1),
    findings=st.text(max_size=40),
)
lane_st = st.builds(
    Lane,
    repo=st.sampled_from(("quark-kit", "qresearch")),
    tickets=st.lists(ticket_st, max_size=3).map(tuple),
    pr_status=st.sampled_from(("none", "running", "approved", "objected", "needs_you")),
    pr_tries=st.integers(0, 2),
    busy=st.booleans(),
)
needs_st = st.builds(NeedsYou, key=st.sampled_from(KEYS), reason=st.sampled_from(
    ("verify_failed_twice", "question", "model_failed", "review_rejected_twice", "stalled")), detail=st.text(max_size=30))
state_st = st.builds(
    State,
    prd=st.text(min_size=1, max_size=12),
    phase=st.sampled_from(("flash", "review", "pr", "done")),
    batch=st.integers(0, 3),
    model=st.sampled_from(("", "qwen3.8-flash-next", "qwen3.8-27b-w8a8")),
    lanes=st.lists(lane_st, max_size=2).map(tuple),
    needs_you=st.lists(needs_st, max_size=2).map(tuple),
    load_tries=st.integers(0, 1),
)


def _fixture_state() -> State:
    return State(
        prd="demo",
        phase="review",
        batch=1,
        model="qwen3.8-27b-w8a8",
        lanes=(
            Lane("quark-kit", (TicketState("quark-kit/01", 0),
                               TicketState("quark-kit/02", 1, depends_on=("quark-kit/01",),
                                           status="changes", sha="abcdef01", findings='[{"id": "f1"}]'),
                               TicketState("quark-kit/03", 1, depends_on=("quark-kit/01",))),
                 pr_status="none", busy=True),
            Lane("qresearch", (TicketState("qresearch/01", 0, status="approved", sha="1234"),),
                 pr_status="approved"),
        ),
        needs_you=(NeedsYou("qresearch/02", "verify_failed_twice", "tail..."),),
        load_tries=1,
    )


def test_AC1_state_round_trips_for_a_nested_fixture():
    s = _fixture_state()
    assert state_from_json(to_json(s)) == s


@settings(deadline=None, max_examples=60)
@given(state_st)
def test_AC1_property_state_round_trips_for_generated_states(s):
    assert state_from_json(to_json(s)) == s


def test_AC2_all_classes_are_frozen():
    for cls, args in ((TicketState, ("quark-kit/01", 0)), (Lane, ("quark-kit", ())),
                      (NeedsYou, ("quark-kit/01", "question")), (State, ("demo",)),
                      (Event, ("implemented",)), (Action, ("load_model",))):
        obj = cls(*args)
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(obj, next(iter(obj.__dataclass_fields__)), "mutated")


def test_AC3_to_json_passes_plain_json_dumps():
    s = _fixture_state()
    d = to_json(s)
    text = json.dumps(d)
    assert json.loads(text) == d
    assert json.loads(json.dumps(to_json(s))) == to_json(s)
