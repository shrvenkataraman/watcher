"""StrEnum statuses and phases, validated on load (ticket 08)."""
import json

import pytest
from hypothesis import given, settings
import hypothesis.strategies as st

from watcher import types as wt
from watcher.types import State, TicketState, Lane, state_from_json, to_json

ORACLE_STATUSES = (
    "pending", "running", "implemented", "approved",
    "changes", "fixed", "needs_you", "skipped",
)
ORACLE_PHASES = ("flash", "review", "pr", "done")


def _state(phase="flash", status="pending"):
    t = TicketState(key="r/01", batch=0, status=status)
    return State(prd="p", phase=phase, lanes=(Lane(repo="r", tickets=(t,)),))


def test_AC1_ticket_statuses_tuple_unchanged():
    assert wt.TICKET_STATUSES == ORACLE_STATUSES
    assert tuple(s.value for s in wt.TicketStatus) == ORACLE_STATUSES
    assert tuple(p.value for p in wt.Phase) == ORACLE_PHASES


def test_AC2_phase_is_str_and_json_unchanged():
    assert wt.Phase.FLASH == "flash"
    out = json.dumps(to_json(State(prd="p", phase=wt.Phase.REVIEW)))
    assert '"review"' in out
    assert State(prd="p", phase=wt.Phase.FLASH) == State(prd="p", phase="flash")


@given(st.text().filter(lambda s: s not in ORACLE_PHASES))
@settings(max_examples=50)
def test_AC3_unknown_phase_raises(bad):
    d = to_json(_state())
    d["phase"] = bad
    with pytest.raises(ValueError, match="unknown phase"):
        state_from_json(d)


def test_AC3_flsh_named_in_error():
    d = to_json(_state())
    d["phase"] = "flsh"
    with pytest.raises(ValueError) as e:
        state_from_json(d)
    assert "flsh" in str(e.value)


@given(st.text().filter(lambda s: s not in ORACLE_STATUSES))
@settings(max_examples=50)
def test_AC4_unknown_status_raises(bad):
    d = to_json(_state())
    d["lanes"][0]["tickets"][0]["status"] = bad
    with pytest.raises(ValueError, match="unknown status"):
        state_from_json(d)


def test_AC4_aproved_names_value_and_key():
    d = to_json(_state())
    d["lanes"][0]["tickets"][0]["status"] = "aproved"
    with pytest.raises(ValueError) as e:
        state_from_json(d)
    assert "aproved" in str(e.value) and "r/01" in str(e.value)


@given(st.sampled_from(ORACLE_PHASES), st.sampled_from(ORACLE_STATUSES))
def test_AC3_AC4_valid_values_round_trip(phase, status):
    s = _state(phase, status)
    assert state_from_json(to_json(s)) == s


def test_AC5_core_treats_enum_phase_as_its_string():
    from watcher import core
    from watcher.types import Event, Phase, State
    plain = core.step(State(prd="p", phase="flash"), Event("start"))
    enum = core.step(State(prd="p", phase=Phase.FLASH), Event("start"))
    assert plain == enum
