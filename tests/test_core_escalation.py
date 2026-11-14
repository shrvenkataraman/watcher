"""Core step for Needs-you escalation and user commands (watcher ticket 07)."""
import copy
import json

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule

from tests.ref.model import PHASE_MODEL, ref_step
from watcher.core import step
from watcher.types import Action, Event, Lane, State, TicketState, to_json

FLASH = "qwen3.8-flash-next"
REVIEW = "qwen3.8-27b-w8a8"
TAIL = "verify output tail: 2 failed"


def _norm(obj) -> dict:
    return json.loads(json.dumps(to_json(obj) if hasattr(obj, "__dataclass_fields__") else obj))


def _actions_json(actions) -> list:
    return [json.loads(json.dumps(to_json(a))) for a in actions]


def _state(lanes, batch=0, phase="flash", model=FLASH, prd="demo", needs=(), tries=0) -> State:
    return State(prd=prd, phase=phase, batch=batch, model=model, lanes=lanes,
                 needs_you=needs, load_tries=tries)


def _running_lane(key="a/01", batch=0, **kw):
    return Lane("a", (TicketState(key, batch, status="running", **kw),), busy=True)


def _two_lanes():
    # lane b stays busy so dispatch never ends a phase.
    return (_running_lane(), Lane("b", (TicketState("b/01", 0, status="running"),), busy=True))


def test_AC1_first_verify_failure_retries_with_the_failure_tail():
    s = _state(_two_lanes())
    new, actions = step(s, Event("implemented", key="a/01", ok=False, detail=TAIL))
    t = new.lanes[0].tickets[0]
    assert t.status == "running" and t.verify_fails == 1  # re-dispatched
    assert [(a.kind, a.key, a.detail) for a in actions] == [("implement", "a/01", TAIL)]


def test_AC1_second_verify_failure_parks_verify_failed_twice():
    ticket = TicketState("a/01", 0, status="running", verify_fails=1)
    s = _state((Lane("a", (ticket,), busy=True),) + _two_lanes()[1:])
    new, actions = step(s, Event("implemented", key="a/01", ok=False, detail=TAIL))
    assert new.lanes[0].tickets[0].status == "needs_you"
    assert [(n.key, n.reason) for n in new.needs_you] == [("a/01", "verify_failed_twice")]
    notifies = [a for a in actions if a.kind == "notify"]
    assert [(a.key, a.detail) for a in notifies] == [("a/01", "verify_failed_twice: a/01")]


def test_AC1_changes_ticket_fails_back_to_changes():
    ticket = TicketState("a/01", 0, status="running", findings='[{"id":"f"}]', fix_rounds=1)
    s = _state((Lane("a", (ticket,), busy=True),) + _two_lanes()[1:])
    new, actions = step(s, Event("fixed", key="a/01", ok=False, detail=TAIL))
    assert new.lanes[0].tickets[0].status == "running"  # re-dispatched as fix
    assert [(a.kind, a.key, a.detail) for a in actions] == [("fix", "a/01", TAIL)]


def test_AC2_park_events_give_matching_reason_and_one_notify():
    for kind, reason in (("question", "question"), ("timeout", "stalled"),
                         ("bad_verdict", "bad_verdict")):
        s = _state(_two_lanes())
        new, actions = step(s, Event(kind, key="a/01", detail="d"))
        assert new.lanes[0].tickets[0].status == "needs_you"
        assert [(n.key, n.reason) for n in new.needs_you] == [("a/01", reason)]
        notifies = [a for a in actions if a.kind == "notify"]
        assert len(notifies) == 1
        assert notifies[0].detail == f"{reason}: a/01"


def test_AC3_model_failed_retries_once_then_parks_model():
    s = _state(_two_lanes())
    new, actions = step(s, Event("model_failed", detail="502"))
    assert actions == (Action("load_model", model=FLASH),)
    assert new.load_tries == 1 and new.needs_you == ()
    new2, actions2 = step(new, Event("model_failed", detail="502"))
    assert [(n.key, n.reason) for n in new2.needs_you] == [("model", "model_failed")]
    assert [a.kind for a in actions2] == ["notify"]


def test_AC4_answered_requeues_and_clears_entries():
    ticket = TicketState("a/01", 0, status="needs_you")
    from watcher.types import NeedsYou
    s = _state((Lane("a", (ticket,), busy=False),) + _two_lanes()[1:],
               needs=(NeedsYou("a/01", "question", "d"),))
    new, actions = step(s, Event("answered", key="a/01"))
    assert new.lanes[0].tickets[0].status == "running"  # answered -> pending -> dispatch marks running
    assert new.needs_you == ()
    assert [(a.kind, a.key) for a in actions] == [("implement", "a/01")]


def test_AC4_retry_model_clears_and_reloads():
    from watcher.types import NeedsYou
    s = _state(_two_lanes(), needs=(NeedsYou("model", "model_failed", ""),), tries=2)
    new, actions = step(s, Event("retry", key="model"))
    assert new.needs_you == () and new.load_tries == 0
    assert actions == (Action("load_model", model=FLASH),)


def test_AC4_skip_marks_skipped_and_removes_entries():
    from watcher.types import NeedsYou
    ticket = TicketState("a/01", 0, status="needs_you")
    s = _state((Lane("a", (ticket,), busy=False),) + _two_lanes()[1:],
               needs=(NeedsYou("a/01", "stalled", ""),))
    new, actions = step(s, Event("skip", key="a/01"))
    assert new.lanes[0].tickets[0].status == "skipped"
    assert new.needs_you == ()


def test_AC4_skipped_and_needs_you_do_not_block_phase_end():
    from watcher.types import NeedsYou
    lane = Lane("a", (TicketState("a/01", 0, status="skipped"),
                      TicketState("a/02", 0, status="needs_you")), busy=False)
    s = _state((lane,), needs=(NeedsYou("a/02", "stalled", ""),))
    new, actions = step(s, Event("start"))
    # nothing dispatchable: flash phase ends into review
    assert new.phase == "review"
    assert actions == (Action("load_model", model=REVIEW),)


def test_AC5_abort_gives_done_and_only_write_summary():
    s = _state(_two_lanes())
    new, actions = step(s, Event("abort"))
    assert new.phase == "done"
    assert actions == (Action("write_summary"),)


def test_phase_timeout_parks_every_running_ticket():
    s = _state(_two_lanes())
    new, actions = step(s, Event("phase_timeout"))
    assert [t.status for lane in new.lanes for t in lane.tickets] == ["needs_you", "needs_you"]
    assert sorted(n.reason for n in new.needs_you) == ["stalled", "stalled"]
    assert sorted(a.key for a in actions if a.kind == "notify") == ["a/01", "b/01"]


lane_cfg_st = st.lists(
    st.lists(st.tuples(st.integers(0, 1)), min_size=1, max_size=3),
    min_size=1, max_size=2,
)


class EscalationMachine(RuleBasedStateMachine):
    """Differential across flash/review with failure, park and user-command events."""

    @initialize(cfg=lane_cfg_st)
    def build(self, cfg):
        lanes = tuple(
            Lane(f"repo{i}", tuple(TicketState(f"repo{i}/{j + 1:02d}", b) for j, (b,) in enumerate(specs)))
            for i, specs in enumerate(cfg)
        )
        self.state = _state(lanes, model="")
        self.ref = json.loads(json.dumps(to_json(self.state)))

    def _apply(self, ev_json: dict):
        ev = Event(**ev_json)
        new, actions = step(self.state, ev)
        ref_new, ref_actions = ref_step(copy.deepcopy(self.ref), ev_json)
        assert _norm(new) == ref_new, (ev_json, _norm(new), ref_new)
        assert _actions_json(actions) == ref_actions, (ev_json, _actions_json(actions), ref_actions)
        # property: needs_you entries == needs_you tickets (+ model when parked)
        ticket_keys = {t.key for lane in new.lanes for t in lane.tickets if t.status == "needs_you"}
        entry_keys = {n.key for n in new.needs_you}
        assert entry_keys - ticket_keys <= {"model"}
        assert ticket_keys <= entry_keys
        # every NeedsYou append came with exactly one notify
        ref_ticket_keys = {t["key"] for lane in ref_new["lanes"] for t in lane["tickets"]
                           if t["status"] == "needs_you"}
        assert entry_keys == ref_ticket_keys or entry_keys - ref_ticket_keys <= {"model"}
        self.state = new
        self.ref = ref_new

    @rule()
    def start(self):
        self._apply({"kind": "start", "key": "", "ok": True, "sha": "", "detail": ""})

    @rule(data=st.data())
    def model_ready(self, data):
        detail = data.draw(st.sampled_from((PHASE_MODEL[self.state.phase] or "", "wrong", "")))
        self._apply({"kind": "model_ready", "key": "", "ok": True, "sha": "", "detail": detail})

    @rule(data=st.data())
    def model_failed(self, data):
        self._apply({"kind": "model_failed", "key": "", "ok": True, "sha": "",
                     "detail": data.draw(st.sampled_from(("502", "engine dead")))})

    @rule(data=st.data())
    def worker_result(self, data):
        running = [t.key for lane in self.state.lanes for t in lane.tickets if t.status == "running"]
        if not running or self.state.phase not in ("flash", "review"):
            return
        key = data.draw(st.sampled_from(running))
        kind = data.draw(st.sampled_from(("implemented", "fixed", "reviewed")))
        ok = data.draw(st.booleans())
        self._apply({"kind": kind, "key": key, "ok": ok, "sha": "abc12345", "detail": TAIL})

    @rule(data=st.data())
    def park_event(self, data):
        running = [t.key for lane in self.state.lanes for t in lane.tickets if t.status == "running"]
        if not running:
            return
        key = data.draw(st.sampled_from(running))
        kind = data.draw(st.sampled_from(("question", "timeout", "bad_verdict")))
        self._apply({"kind": kind, "key": key, "ok": True, "sha": "", "detail": "why"})

    @rule(data=st.data())
    def user_command(self, data):
        if not self.state.needs_you:
            return
        key = data.draw(st.sampled_from(tuple(sorted({n.key for n in self.state.needs_you}))))
        kind = data.draw(st.sampled_from(("answered", "retry", "skip")))
        self._apply({"kind": kind, "key": key, "ok": True, "sha": "", "detail": ""})

    @rule()
    def phase_timeout(self):
        self._apply({"kind": "phase_timeout", "key": "", "ok": True, "sha": "", "detail": ""})


TestEscalation = EscalationMachine.TestCase
TestEscalation.settings = settings(max_examples=40, stateful_step_count=12, deadline=None)
