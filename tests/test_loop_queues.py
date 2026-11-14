"""Tick publishes queue counts and role (multi-project ticket 14)."""
import json
import os

from hypothesis import given, strategies as st

from watcher import lease as lm
from watcher.loop import PHASE_ROLE, queue_counts
from watcher.types import Lane, State, TicketState


def _s(*tickets, pr="none", phase="flash"):
    lane = Lane("a", tuple(tickets), pr_status=pr)
    return State(prd="p", phase=phase, batch=0, model="m", lanes=(lane,))


def test_AC1_counts():
    s = _s(TicketState("a/1", 0), TicketState("a/2", 0, status="changes"),
           TicketState("a/3", 0, status="implemented"), TicketState("a/4", 0, status="approved"))
    assert queue_counts(s) == {"working": 2, "review": 1, "pr": 0}


def test_AC2_blocked_dependents_are_not_working():
    for st_ in ("needs_you", "skipped"):
        s = _s(TicketState("a/1", 0, status=st_), TicketState("a/2", 0, depends_on=("a/1",)))
        assert queue_counts(s)["working"] == 0


def test_AC3_pr_count():
    t = (TicketState("a/1", 0, status="approved"),)
    assert queue_counts(_s(*t, pr="none"))["pr"] == 1
    assert queue_counts(_s(*t, pr="approved"))["pr"] == 0


def test_AC4_phase_role_map():
    assert PHASE_ROLE == {"flash": "working", "review": "review", "pr": "pr"}


def test_AC5_clear_removes_a_finished_project(tmp_path):
    lm.publish(str(tmp_path), "p", queue_counts(_s(TicketState("a/1", 0))))
    assert lm.totals(str(tmp_path))["working"] == 1
    lm.clear(str(tmp_path), "p")
    assert lm.totals(str(tmp_path))["working"] == 0


def test_AC6_review_project_waits_for_flash_project(tmp_path):
    d = str(tmp_path)
    lm.publish(d, "flash-proj", queue_counts(_s(TicketState("a/1", 0))))
    lm.publish(d, "review-proj", queue_counts(_s(TicketState("b/1", 0, status="implemented"))))
    rv = lm.Lease(d, sleep=lambda _s: None, poll=0)
    try:
        rv.acquire("r", timeout=0, role="review")
        raise AssertionError("review must wait")
    except lm.LeaseTimeout:
        pass
    lm.clear(d, "flash-proj")
    rv.acquire("r", timeout=0, role="review")
    assert rv.held() == "r"


@given(st.lists(st.sampled_from(["pending", "changes", "implemented", "approved", "skipped"]), max_size=8))
def test_AC1_property_counts_bounded(statuses):
    s = _s(*[TicketState(f"a/{i}", 0, status=x) for i, x in enumerate(statuses)])
    c = queue_counts(s)
    assert c["working"] + c["review"] <= len(statuses)
