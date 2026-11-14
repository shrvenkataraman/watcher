"""Resume reconcile: git history is the truth about committed tickets (watcher ticket 14)."""
import pytest
from hypothesis import given, settings
import hypothesis.strategies as st

from watcher.resume import reconcile
from watcher.types import Lane, NeedsYou, State, TicketState

COMMITTED = {"quark-kit": {"quark-kit/01": "shaA11111", "quark-kit/03": "shaC33333"}}


def _tickets(*specs) -> tuple:
    return tuple(TicketState(**s) for s in specs)


def _fixture() -> State:
    return State(
        prd="demo",
        phase="flash",
        batch=0,
        model="qwen3.8-flash-next",
        lanes=(
            Lane("quark-kit", _tickets(
                {"key": "quark-kit/01", "batch": 0, "status": "running"},
                {"key": "quark-kit/02", "batch": 0, "status": "running", "findings": '[{"id":"f"}]',
                 "fix_rounds": 1},
                {"key": "quark-kit/03", "batch": 0, "status": "pending"},
                {"key": "quark-kit/04", "batch": 1, "status": "approved", "sha": "keep111"},
            ), busy=True, pr_status="running"),
            Lane("qresearch", _tickets(
                {"key": "qresearch/01", "batch": 0, "status": "running", "findings": '[{"id":"f"}]'},
                {"key": "qresearch/02", "batch": 0, "status": "needs_you"},
                {"key": "qresearch/03", "batch": 0, "status": "skipped"},
                {"key": "qresearch/04", "batch": 0, "status": "running"},
            ), pr_status="fixing"),
        ),
        needs_you=(NeedsYou("qresearch/02", "question", "?"),),
        load_tries=1,
    )


def test_AC1_running_with_a_commit_becomes_implemented_with_that_sha():
    out = reconcile(_fixture(), COMMITTED)
    t01 = out.lanes[0].tickets[0]
    assert t01.status == "implemented" and t01.sha == "shaA11111"


def test_AC1_pending_with_a_commit_becomes_implemented():
    out = reconcile(_fixture(), COMMITTED)
    t03 = out.lanes[0].tickets[2]
    assert t03.status == "implemented" and t03.sha == "shaC33333"


def test_AC1_fix_in_flight_with_its_commit_becomes_implemented():
    out = reconcile(_fixture(), {"quark-kit": {"quark-kit/02": "shaB22222"}})
    t02 = out.lanes[0].tickets[1]
    assert t02.status == "implemented" and t02.sha == "shaB22222"


def test_AC2_running_without_a_commit_becomes_pending():
    out = reconcile(_fixture(), COMMITTED)
    t04 = out.lanes[1].tickets[3]
    assert t04.status == "pending" and t04.sha == ""


def test_AC2_running_fix_that_was_never_committed_goes_back_to_changes():
    # running, non-empty findings, fix_rounds == 0, no commit -> changes again.
    out = reconcile(_fixture(), COMMITTED)
    t = out.lanes[1].tickets[0]
    assert t.status == "changes"


def test_AC3_approved_needs_you_skipped_are_untouched():
    out = reconcile(_fixture(), COMMITTED)
    assert out.lanes[0].tickets[3].status == "approved" and out.lanes[0].tickets[3].sha == "keep111"
    assert out.lanes[1].tickets[1].status == "needs_you"
    assert out.lanes[1].tickets[2].status == "skipped"
    assert out.needs_you == _fixture().needs_you


def test_AC4_lanes_are_freed_prs_reset_and_model_cleared():
    out = reconcile(_fixture(), COMMITTED)
    assert all(not lane.busy for lane in out.lanes)
    assert out.lanes[0].pr_status == "none"      # was running
    assert out.lanes[1].pr_status == "objected:"  # was fixing
    assert out.model == ""


ticket_st = st.builds(
    TicketState,
    key=st.sampled_from(("a/01", "a/02", "b/01")),
    batch=st.integers(0, 1),
    status=st.sampled_from(("pending", "running", "implemented", "approved", "changes",
                            "fixed", "needs_you", "skipped")),
    sha=st.sampled_from(("", "aaa111")),
    findings=st.sampled_from(("", '[{"id":"f"}]')),
    fix_rounds=st.integers(0, 1),
)
state_st = st.builds(
    State,
    prd=st.just("demo"),
    lanes=st.just((Lane("a", (TicketState("a/01", 0), TicketState("a/02", 0))),
                   Lane("b", (TicketState("b/01", 0),)))),
    model=st.sampled_from(("", "m")),
)
committed_st = st.fixed_dictionaries({
    "a": st.fixed_dictionaries({"key": st.just("01")}).flatmap(
        lambda _: st.fixed_dictionaries({"a/01": st.just("aaa111"), "a/02": st.just("bbb222")})),
    "b": st.just({}),
})


@settings(deadline=None, max_examples=60)
@given(state_st, committed_st)
def test_properties_idempotence_no_running_no_pending_committed(s, committed):
    once = reconcile(s, committed)
    assert reconcile(once, committed) == once          # idempotent
    assert not any(t.status == "running" for lane in once.lanes for t in lane.tickets)
    flat = {t.key for lane in once.lanes for t in lane.tickets if t.status == "pending"}
    committed_keys = {k for repo in committed.values() for k in repo}
    assert not (flat & committed_keys)                 # committed keys are never pending again
    assert all(not lane.busy for lane in once.lanes) and once.model == ""
