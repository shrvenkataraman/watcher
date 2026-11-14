"""Core step for fix dispatch in the flash phase, differential vs the reference (watcher ticket 06)."""
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
GLM = "glm-5.3-flash-maya"


def _norm(obj) -> dict:
    return json.loads(json.dumps(to_json(obj) if hasattr(obj, "__dataclass_fields__") else obj))


def _actions_json(actions) -> list:
    return [json.loads(json.dumps(to_json(a))) for a in actions]


def _state(lanes, batch=0, phase="flash", model="", prd="demo") -> State:
    return State(prd=prd, phase=phase, batch=batch, model=model, lanes=lanes)


FINDINGS = '[{"id": "f1", "problem": "x"}]'


def test_AC1_changes_beat_pending_in_the_same_lane():
    lane = Lane("a", (TicketState("a/02", 0), TicketState("a/01", 0, status="changes",
                                                          findings=FINDINGS)))
    s = _state((lane,))
    new, actions = step(s, Event("model_ready", detail=FLASH))
    assert len(actions) == 1
    a = actions[0]
    assert (a.kind, a.key, a.model, a.detail) == ("fix", "a/01", FLASH, FINDINGS)
    assert new.lanes[0].busy is True
    assert new.lanes[0].tickets[1].status == "running"
    assert new.lanes[0].tickets[0].status == "pending"


def test_AC2_fixed_sets_status_sha_and_fix_round():
    lane = Lane("a", (TicketState("a/01", 0, status="running", findings=FINDINGS),), busy=True)
    s = _state((lane,))
    new, actions = step(s, Event("fixed", key="a/01", ok=True, sha="ff99aa"))
    t = new.lanes[0].tickets[0]
    assert t.status == "fixed" and t.sha == "ff99aa" and t.fix_rounds == 1
    assert new.lanes[0].busy is False
    # nothing else reviewable or ready in this single lane -> flash phase ends into review.
    assert actions == (Action("load_model", model=REVIEW),)


def test_AC3_review_phase_reviews_fixed_and_implemented_together():
    lane = Lane("a", (TicketState("a/01", 0, status="fixed", sha="ff99aa"),
                      TicketState("a/02", 0, status="implemented", sha="ee88bb")))
    s = _state((lane,), phase="review")
    new, actions = step(s, Event("model_ready", detail=REVIEW))
    assert [(a.kind, a.key, a.detail) for a in actions] == [("review", "a/01", "fixed")]
    new2, actions2 = step(new, Event("reviewed", key="a/01", ok=True))
    assert [(a.kind, a.key) for a in actions2] == [("review", "a/02")]
    new3, _ = step(new2, Event("reviewed", key="a/02", ok=True))
    assert [t.status for t in new3.lanes[0].tickets] == ["approved", "approved"]


def test_AC4_a_ticket_never_gets_a_second_fix_action():
    # reject -> changes -> fix -> fixed -> reject -> needs_you (no second fix, no second changes).
    lane = Lane("a", (TicketState("a/01", 0, status="running"),), busy=True)
    s = _state((lane,), phase="review", model=REVIEW)
    s, _ = step(s, Event("reviewed", key="a/01", ok=False, detail=FINDINGS))  # changes, flash
    assert s.phase == "flash"
    s, actions = step(s, Event("model_ready", detail=FLASH))
    assert [(a.kind, a.key) for a in actions] == [("fix", "a/01")]
    s, _ = step(s, Event("fixed", key="a/01", ok=True, sha="ff99aa"))
    assert s.phase == "review"
    s, actions = step(s, Event("model_ready", detail=REVIEW))
    assert [(a.kind, a.key) for a in actions] == [("review", "a/01")]
    s, _ = step(s, Event("reviewed", key="a/01", ok=False, detail=FINDINGS))
    assert s.lanes[0].tickets[0].status == "needs_you"
    assert [n.reason for n in s.needs_you] == ["review_rejected_twice"]
    # phase already moved to pr (nothing left): model_ready there dispatches no fix, ever.
    s, actions = step(s, Event("model_ready", detail=GLM))
    assert actions == ()  # no fix action ever dispatched a second time


lane_cfg_st = st.lists(
    st.lists(st.tuples(st.integers(0, 1)), min_size=1, max_size=3),
    min_size=1, max_size=2,
)


class CoreFixMachine(RuleBasedStateMachine):
    """Differential across flash and review with implement, fix and review verdicts."""

    @initialize(cfg=lane_cfg_st)
    def build(self, cfg):
        lanes = tuple(
            Lane(f"repo{i}", tuple(TicketState(f"repo{i}/{j + 1:02d}", b) for j, (b,) in enumerate(specs)))
            for i, specs in enumerate(cfg)
        )
        self.state = _state(lanes)
        self.ref = json.loads(json.dumps(to_json(self.state)))
        self.fix_actions = {}

    def _apply(self, ev_json: dict):
        ev = Event(**ev_json)
        new, actions = step(self.state, ev)
        ref_new, ref_actions = ref_step(copy.deepcopy(self.ref), ev_json)
        assert _norm(new) == ref_new, (ev_json, _norm(new), ref_new)
        assert _actions_json(actions) == ref_actions, (ev_json, _actions_json(actions), ref_actions)
        for a in actions:
            if a.kind == "fix":
                self.fix_actions[a.key] = self.fix_actions.get(a.key, 0) + 1
        tickets = {t.key: t for lane in new.lanes for t in lane.tickets}
        assert all(fr <= 1 for fr in self.fix_actions.values())
        for key, fr in self.fix_actions.items():
            assert tickets[key].fix_rounds <= 1 or tickets[key].status in ("fixed", "needs_you")
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
    def implemented(self, data):
        running = [t.key for lane in self.state.lanes for t in lane.tickets if t.status == "running"]
        if not running or self.state.phase != "flash":
            return
        key = data.draw(st.sampled_from(running))
        self._apply({"kind": "implemented", "key": key, "ok": True, "sha": "abc12345", "detail": ""})

    @rule(data=st.data())
    def fixed(self, data):
        running = [t.key for lane in self.state.lanes for t in lane.tickets if t.status == "running"]
        if not running or self.state.phase != "flash":
            return
        key = data.draw(st.sampled_from(running))
        self._apply({"kind": "fixed", "key": key, "ok": True, "sha": "def45678", "detail": ""})

    @rule(data=st.data())
    def reviewed(self, data):
        if self.state.phase != "review":
            return
        running = [t.key for lane in self.state.lanes for t in lane.tickets if t.status == "running"]
        if not running:
            return
        key = data.draw(st.sampled_from(running))
        ok = data.draw(st.booleans())
        self._apply({"kind": "reviewed", "key": key, "ok": ok, "sha": "", "detail": FINDINGS})


TestCoreFix = CoreFixMachine.TestCase
TestCoreFix.settings = settings(max_examples=40, stateful_step_count=12, deadline=None)
