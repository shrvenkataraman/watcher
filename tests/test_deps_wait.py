import json
import time

from tests.ref.model import ref_step
from watcher.core import step
from watcher.types import Event, Lane, NeedsYou, State, TicketState, to_json

FLASH = "qwen3.8-flash-next"


def _state(dep_status, needs=()):
    lanes = (Lane("qk", (TicketState("qk/02", 0, depends_on=("qr/01",)),)),
             Lane("qr", (TicketState("qr/01", 0, status=dep_status),)))
    return State(prd="demo", phase="flash", batch=0, model=FLASH, lanes=lanes, needs_you=needs)


def _parked():
    return _state("needs_you", (NeedsYou("qr/01", "question", "why"),))


def test_AC1_needs_you_dependency_leaves_dependents_pending():
    new, actions = step(_parked(), Event("model_ready", detail=FLASH))
    assert new.lanes[0].tickets[0].status == "pending"
    assert [n.key for n in new.needs_you] == ["qr/01"]
    assert not [a for a in actions if a.kind == "notify"]


def test_AC2_skipped_dependency_still_parks_dependents():
    new, _ = step(_state("skipped"), Event("model_ready", detail=FLASH))
    assert new.lanes[0].tickets[0].status == "needs_you"
    assert any(n.key == "qk/02" and n.reason == "dependency_blocked" for n in new.needs_you)


def test_AC3_dependents_dispatch_after_dependency_is_approved():
    s, _ = step(_parked(), Event("model_ready", detail=FLASH))
    s, actions = step(s, Event("answered", key="qr/01"))
    assert ("implement", "qr/01") in [(a.kind, a.key) for a in actions]
    s, _ = step(s, Event("implemented", key="qr/01", ok=True, sha="abc12345"))
    s, _ = step(s, Event("model_ready", detail="qwen3.8-27b-w8a8"))
    s, actions = step(s, Event("reviewed", key="qr/01", ok=True))
    s, more = step(s, Event("model_ready", detail=FLASH))
    assert ("implement", "qk/02") in [(a.kind, a.key) for a in actions + more]


def test_AC4_phase_idles_while_dependent_waits_on_needs_you():
    new, actions = step(_parked(), Event("model_ready", detail=FLASH))
    assert new.phase == "flash"
    assert not [a for a in actions if a.kind == "load_model"]
    ref_new, _ = ref_step(json.loads(json.dumps(to_json(_parked()))),
                          {"kind": "model_ready", "key": "", "ok": True, "sha": "", "detail": FLASH})
    assert ref_new["phase"] == "flash"
    assert json.loads(json.dumps(to_json(new))) == ref_new


def _lattice_state(n):
    t = [TicketState("a/00", 0, status="implemented")] + [TicketState(
        f"a/{i:02d}", 0, depends_on=tuple(f"a/{j:02d}" for j in (i - 1, i - 2) if j >= 0))
        for i in range(1, n + 1)]
    return State(prd="demo", phase="flash", batch=0, model=FLASH, lanes=(Lane("a", tuple(t)),))


def test_AC4_lattice_of_40_tickets_steps_in_under_one_second():
    t0 = time.monotonic()
    step(_lattice_state(40), Event("model_ready", detail=FLASH))
    assert time.monotonic() - t0 < 1.0


def test_AC4_chain_of_2000_tickets_does_not_raise():
    t = [TicketState("c/0000", 0, status="needs_you")] + [
        TicketState(f"c/{i:04d}", 0, depends_on=(f"c/{i - 1:04d}",)) for i in range(1, 2000)]
    s = State(prd="demo", phase="flash", batch=0, model=FLASH, lanes=(Lane("c", tuple(t)),))
    assert step(s, Event("model_ready", detail=FLASH))[0].phase == "flash"


REVIEW = "qwen3.8-27b-w8a8"


def _ref(state, kind, key="", ok=True, sha="", detail=""):
    """Run the reference model on the same state and event; return (state, actions)."""
    return ref_step(json.loads(json.dumps(to_json(state))),
                    {"kind": kind, "key": key, "ok": ok, "sha": sha, "detail": detail})


def _assert_same_watcher_and_ref(new, ref_new):
    assert json.loads(json.dumps(to_json(new))) == ref_new


def test_AC4_review_does_not_leave_for_pr_while_a_ticket_waits():
    lanes = (Lane("qk", (TicketState("qk/01", 0, status="approved"),
                         TicketState("qk/02", 0, depends_on=("qk/03",)),
                         TicketState("qk/03", 0, status="needs_you"))),)
    s = State(prd="demo", phase="review", batch=0, model=REVIEW, lanes=lanes,
              needs_you=(NeedsYou("qk/03", "question", "why"),))
    new, actions = step(s, Event("model_ready", detail=REVIEW))
    assert new.phase == "review"
    assert not [a for a in actions if a.kind in ("load_model", "write_summary")]
    ref_new, _ = _ref(s, "model_ready", detail=REVIEW)
    assert ref_new["phase"] == "review"
    _assert_same_watcher_and_ref(new, ref_new)


def test_AC5_skipped_chain_parks_every_dependent_in_one_step():
    lanes = (Lane("a", (TicketState("a/01", 0, status="skipped"),
                        TicketState("a/02", 0, depends_on=("a/01",)),
                        TicketState("a/03", 0, depends_on=("a/02",)))),)
    s = State(prd="demo", phase="flash", batch=0, model=FLASH, lanes=lanes)
    new, actions = step(s, Event("model_ready", detail=FLASH))
    assert {t.key: t.status for t in new.lanes[0].tickets} == {
        "a/01": "skipped", "a/02": "needs_you", "a/03": "needs_you"}
    parked = {n.key: (n.reason, n.detail) for n in new.needs_you}
    assert parked == {"a/02": ("dependency_blocked", "a/01"),
                      "a/03": ("dependency_blocked", "a/02")}
    assert sorted(a.key for a in actions if a.kind == "notify") == ["a/02", "a/03"]
    ref_new, _ = _ref(s, "model_ready", detail=FLASH)
    _assert_same_watcher_and_ref(new, ref_new)


def test_AC5_second_step_parks_a_dependent_added_behind_a_blocked_one():
    lanes = (Lane("a", (TicketState("a/01", 0, status="skipped"),
                        TicketState("a/02", 0, depends_on=("a/01",), status="needs_you"),
                        TicketState("a/03", 0, depends_on=("a/02",)))),)
    s = State(prd="demo", phase="flash", batch=0, model=FLASH, lanes=lanes,
              needs_you=(NeedsYou("a/02", "dependency_blocked", "a/01"),))
    new, _ = step(s, Event("model_ready", detail=FLASH))
    assert new.lanes[0].tickets[2].status == "needs_you"
    assert any(n.key == "a/03" and n.reason == "dependency_blocked" for n in new.needs_you)
    ref_new, _ = _ref(s, "model_ready", detail=FLASH)
    _assert_same_watcher_and_ref(new, ref_new)


def test_AC6_pr_reviewed_does_not_reach_done_while_a_ticket_waits():
    lanes = (Lane("qr", (TicketState("qr/01", 0, status="approved"),),
                 pr_status="running", busy=True),
             Lane("qk", (TicketState("qk/01", 0, status="approved"),
                         TicketState("qk/02", 0, depends_on=("qk/03",)),
                         TicketState("qk/03", 0, status="needs_you")),
                 pr_status="approved"))
    s = State(prd="demo", phase="pr", batch=0, model="glm-5.3-flash-maya", lanes=lanes,
              needs_you=(NeedsYou("qk/03", "question", "why"),))
    new, actions = step(s, Event("pr_reviewed", key="qr", ok=True))
    assert new.phase == "pr"
    assert not [a for a in actions if a.kind == "write_summary"]
    assert any(n.key == "qk/03" for n in new.needs_you)
    ref_new, ref_actions = _ref(s, "pr_reviewed", key="qr")
    assert ref_new["phase"] == "pr"
    assert not [a for a in ref_actions if a["kind"] == "write_summary"]
    _assert_same_watcher_and_ref(new, ref_new)


def test_AC6_done_still_happens_when_nothing_waits():
    lanes = (Lane("qr", (TicketState("qr/01", 0, status="approved"),),
                 pr_status="running", busy=True),)
    s = State(prd="demo", phase="pr", batch=0, model="glm-5.3-flash-maya", lanes=lanes)
    new, actions = step(s, Event("pr_reviewed", key="qr", ok=True))
    assert new.phase == "done"
    assert [a.kind for a in actions] == ["open_pr", "write_summary"]
    ref_new, _ = _ref(s, "pr_reviewed", key="qr")
    _assert_same_watcher_and_ref(new, ref_new)
