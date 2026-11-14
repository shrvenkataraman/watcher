"""Core depends_on gating: approved-only dispatch, dependency_blocked parking (ticket 08)."""
import copy
import json

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule

from tests.ref.model import PHASE_MODEL, ref_step
from watcher.core import step
from watcher.types import Action, Event, Lane, NeedsYou, State, TicketState, to_json

FLASH = "qwen3.8-flash-next"
REVIEW = "qwen3.8-27b-w8a8"
GLM = "glm-5.3-flash-maya"


def _norm(obj) -> dict:
    return json.loads(json.dumps(to_json(obj) if hasattr(obj, "__dataclass_fields__") else obj))


def _actions_json(actions) -> list:
    return [json.loads(json.dumps(to_json(a))) for a in actions]


def _state(lanes, batch=0, phase="flash", model="", prd="demo", needs=()):
    return State(prd=prd, phase=phase, batch=batch, model=model, lanes=lanes, needs_you=needs)


def _dep(depends, batch=0, status="pending"):
    return TicketState("qk/02", batch, status=status, depends_on=depends)


def _two_lanes(qk_ticket, qr_ticket, needs=()):
    return _state((Lane("qk", (qk_ticket,)), Lane("qr", (qr_ticket,))), needs=needs)


def test_AC1_unapproved_dependency_blocks_dispatch():
    s = _two_lanes(_dep(("qr/01",)), TicketState("qr/01", 0))
    new, actions = step(s, Event("model_ready", detail=FLASH))
    assert [(a.kind, a.key) for a in actions] == [("implement", "qr/01")]
    assert new.lanes[0].tickets[0].status == "pending"


def test_AC2_approved_dependency_dispatches_the_dependent():
    dep = TicketState("qr/01", 0, status="approved", sha="aa1")
    s = _two_lanes(_dep(("qr/01",)), dep)
    new, actions = step(s, Event("model_ready", detail=FLASH))
    assert [(a.kind, a.key) for a in actions] == [("implement", "qk/02")]


def test_AC3_parked_dependency_parks_the_dependent():
    dep = TicketState("qr/01", 0, status="needs_you")
    s = _two_lanes(_dep(("qr/01",)), dep, needs=(NeedsYou("qr/01", "question", "why"),))
    new, actions = step(s, Event("model_ready", detail=FLASH))
    parked = new.lanes[0].tickets[0]
    assert parked.status == "needs_you"
    entry = next(n for n in new.needs_you if n.key == "qk/02")
    assert entry.reason == "dependency_blocked" and entry.detail == "qr/01"
    notify = next(a for a in actions if a.kind == "notify" and a.key == "qk/02")
    assert notify.detail == "dependency_blocked: qk/02"


def test_AC3_skipped_dependency_parks_the_dependent():
    dep = TicketState("qr/01", 0, status="skipped")
    s = _two_lanes(_dep(("qr/01",)), dep)
    new, actions = step(s, Event("model_ready", detail=FLASH))
    assert new.lanes[0].tickets[0].status == "needs_you"
    assert any(n.reason == "dependency_blocked" for n in new.needs_you)


def test_AC4_waiting_ticket_does_not_block_a_later_independent_one():
    first = TicketState("qk/01", 0, depends_on=("qr/01",))
    second = TicketState("qk/02", 0)
    s = _state((Lane("qk", (first, second)), Lane("qr", (TicketState("qr/01", 0),))))
    new, actions = step(s, Event("model_ready", detail=FLASH))
    pairs = [(a.kind, a.key) for a in actions]
    assert ("implement", "qk/02") in pairs
    assert ("implement", "qr/01") in pairs
    assert ("implement", "qk/01") not in pairs


class DependsMachine(RuleBasedStateMachine):
    """Cross-lane deps: a/02 needs b/01, b/02 needs a/01."""

    @initialize()
    def build(self):
        lanes = (
            Lane("a", (TicketState("a/01", 0),
                       TicketState("a/02", 0, depends_on=("b/01",)))),
            Lane("b", (TicketState("b/01", 0),
                       TicketState("b/02", 0, depends_on=("a/01",)))),
        )
        self.state = _state(lanes)
        self.ref = json.loads(json.dumps(to_json(self.state)))

    def _apply(self, ev_json: dict):
        pre = copy.deepcopy(self.ref)
        ev = Event(**ev_json)
        new, actions = step(self.state, ev)
        ref_new, ref_actions = ref_step(copy.deepcopy(self.ref), ev_json)
        assert _norm(new) == ref_new, (ev_json, _norm(new), ref_new)
        assert _actions_json(actions) == ref_actions, (ev_json, _actions_json(actions), ref_actions)
        # every implement action: all its deps are approved at dispatch time (post-event state);
        # an event may legitimately approve a dependency within the same step before dispatch.
        new_status = {t.key: t.status for lane in new.lanes for t in lane.tickets}
        new_deps = {t.key: t.depends_on for lane in new.lanes for t in lane.tickets}
        for a in actions:
            if a.kind == "implement":
                assert all(new_status.get(d) == "approved" for d in new_deps[a.key]), (a, new_status)
        # no pending ticket ever keeps a skipped or needs_you dependency
        for lane in new.lanes:
            for t in lane.tickets:
                if t.status == "pending":
                    dep_status = {d: next(x.status for ln in new.lanes for x in ln.tickets
                                          if x.key == d) for d in t.depends_on}
                    assert not any(v in ("skipped", "needs_you") for v in dep_status.values()), t
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
    def worker_result(self, data):
        running = [t.key for lane in self.state.lanes for t in lane.tickets if t.status == "running"]
        if not running or self.state.phase not in ("flash", "review"):
            return
        key = data.draw(st.sampled_from(running))
        kind = data.draw(st.sampled_from(("implemented", "reviewed")))
        ok = data.draw(st.booleans())
        self._apply({"kind": kind, "key": key, "ok": ok, "sha": "abc12345", "detail": "tail"})

    @rule(data=st.data())
    def park_or_release(self, data):
        tickets = [t.key for lane in self.state.lanes for t in lane.tickets
                   if t.status in ("running", "needs_you")]
        if not tickets:
            return
        key = data.draw(st.sampled_from(sorted(tickets)))
        kind = data.draw(st.sampled_from(("question", "timeout", "skip", "answered", "retry")))
        self._apply({"kind": kind, "key": key, "ok": True, "sha": "", "detail": "d"})

    @rule()
    def model_failed(self):
        self._apply({"kind": "model_failed", "key": "", "ok": True, "sha": "", "detail": "502"})


TestDepends = DependsMachine.TestCase
TestDepends.settings = settings(max_examples=40, stateful_step_count=12, deadline=None)


def test_dependency_approved_in_review_goes_back_to_flash_not_pr():
    from watcher.core import step
    from watcher.types import Event, Lane, State, TicketState
    lane = Lane("a", (TicketState("a/01", 0, status="running", sha="s1"),
                      TicketState("a/02", 0, depends_on=("a/01",))), busy=True)
    s = State(prd="d", phase="review", model="qwen3.8-27b-w8a8", lanes=(lane,))
    new, actions = step(s, Event("reviewed", key="a/01", ok=True, detail="[]"))
    assert new.phase == "flash"
    assert [a.model for a in actions if a.kind == "load_model"] == ["qwen3.8-flash-next"]
