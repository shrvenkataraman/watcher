"""Requeue blocked working tickets (multi-project ticket 15)."""
from hypothesis import given, strategies as st

from watcher.core import step
from watcher.types import Event, Lane, State, TicketState

FLASH = "qwen3.8-flash-next"
STATUSES = ["pending", "running", "implemented", "approved", "changes", "needs_you", "skipped"]


def _s(a_status, b_status, **kw):
    lane = Lane("q", (TicketState("q/1", 0, status=a_status),
                      TicketState("q/2", 0, status=b_status, depends_on=("q/1",), **kw)))
    return State(prd="d", phase="flash", batch=0, model=FLASH, lanes=(lane,))


def _b(s):
    return s.lanes[0].tickets[1]


def test_AC1_running_goes_pending():
    new, _ = step(_s("needs_you", "running"), Event("model_ready", detail=FLASH))
    assert _b(new).status == "pending"


def test_AC2_changes_goes_pending():
    new, _ = step(_s("needs_you", "changes"), Event("model_ready", detail=FLASH))
    assert _b(new).status == "pending"


def test_AC3_met_dependency_keeps_running():
    new, _ = step(_s("implemented", "running"), Event("model_ready", detail=FLASH))
    assert _b(new).status == "running"


def test_AC4_fix_rounds_and_sha_kept():
    new, _ = step(_s("needs_you", "running", fix_rounds=2, sha="abc"), Event("model_ready", detail=FLASH))
    assert (_b(new).fix_rounds, _b(new).sha) == (2, "abc")


def test_AC5_no_notify_no_needs_you_entry():
    new, actions = step(_s("needs_you", "running"), Event("model_ready", detail=FLASH))
    assert not [a for a in actions if a.kind == "notify" and a.key == "q/2"]
    assert not [n for n in new.needs_you if n.key == "q/2"]


def test_AC6_dispatched_after_dependency_approved():
    s, _ = step(_s("needs_you", "running"), Event("model_ready", detail=FLASH))
    s, actions = step(s, Event("answered", key="q/1"))
    s, _ = step(s, Event("implemented", key="q/1", ok=True, sha="a1"))
    s, _ = step(s, Event("model_ready", detail="qwen3.8-27b-w8a8"))
    s, more = step(s, Event("reviewed", key="q/1", ok=True))
    s, more2 = step(s, Event("model_ready", detail=FLASH))
    assert ("implement", "q/2") in [(a.kind, a.key) for a in actions + more + more2]


@given(a=st.sampled_from(STATUSES), b=st.sampled_from(STATUSES))
def test_AC1_property_no_running_behind_needs_you(a, b):
    new, _ = step(_s(a, b), Event("model_ready", detail=FLASH))
    t = new.lanes[0].tickets
    if t[0].status == "needs_you":
        assert t[1].status not in ("running", "changes")
