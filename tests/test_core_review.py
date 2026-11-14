"""Core step for the review phase, differential against the dict reference (watcher ticket 05)."""
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


def _tickets(*specs) -> tuple:
    return tuple(TicketState(key=k, batch=b) for k, b in specs)


def _state(lanes, batch=0, phase="flash", model="", prd="demo") -> State:
    return State(prd=prd, phase=phase, batch=batch, model=model, lanes=lanes)


def test_AC1_model_ready_in_review_emits_one_review_per_reviewable_lane():
    lane1 = Lane("a", (TicketState("a/01", 0, status="implemented", sha="aaaa111"),))
    lane2 = Lane("b", (TicketState("b/01", 0, status="fixed", sha="bbbb222"),))
    lane3 = Lane("c", (TicketState("c/01", 0, status="approved", sha="cccc333"),))
    s = _state((lane1, lane2, lane3), phase="review")
    new, actions = step(s, Event("model_ready", detail=REVIEW))
    assert [(a.kind, a.key) for a in actions] == [("review", "a/01"), ("review", "b/01")]
    assert all(a.model == REVIEW for a in actions)
    assert new.lanes[1].tickets[0].status == "running"
    fix_action = next(a for a in actions if a.key == "b/01")
    assert fix_action.detail == "fixed"


def test_AC2_approve_sets_approved_and_reject_round0_sets_changes():
    lane = Lane("a", (TicketState("a/01", 0, status="running"),), busy=True)
    s = _state((lane,), phase="review", model=REVIEW)
    new, _ = step(s, Event("reviewed", key="a/01", ok=True))
    assert new.lanes[0].tickets[0].status == "approved"
    assert new.lanes[0].busy is False

    lane2 = Lane("a", (TicketState("a/01", 0, status="running"),), busy=True)
    s2 = _state((lane2,), phase="review", model=REVIEW)
    findings = '[{"id": "f1"}]'
    new2, _ = step(s2, Event("reviewed", key="a/01", ok=False, detail=findings))
    t = new2.lanes[0].tickets[0]
    assert t.status == "changes" and t.findings == findings


def test_AC3_reject_after_fix_round_parks_review_rejected_twice():
    ticket = TicketState("a/01", 0, status="running", fix_rounds=1)
    s = _state((Lane("a", (ticket,), busy=True),), phase="review", model=REVIEW)
    new, _ = step(s, Event("reviewed", key="a/01", ok=False, detail="[]"))
    assert new.lanes[0].tickets[0].status == "needs_you"
    assert [(n.key, n.reason) for n in new.needs_you] == [("a/01", "review_rejected_twice")]


def test_AC4_more_batches_return_to_flash_and_increment_batch():
    # a/01 approved in batch 0; a/02 pending in batch 1 -> back to flash with batch 1.
    lane = Lane("a", (TicketState("a/01", 0, status="approved", sha="aa11"),
                      TicketState("a/02", 1)), busy=True)
    s = _state((lane,), phase="review", model=REVIEW)
    new, actions = step(s, Event("reviewed", key="a/01", ok=True))
    assert new.phase == "flash" and new.batch == 1
    assert actions == (Action("load_model", model=FLASH),)


def test_AC4_changes_return_to_flash_without_increment():
    # a/01 running gets rejected -> changes; a/02 still pending in batch 0 -> batch does NOT increment.
    lane = Lane("a", (TicketState("a/01", 0, status="running"), TicketState("a/02", 0)), busy=True)
    s = _state((lane,), phase="review", model=REVIEW)
    new, actions = step(s, Event("reviewed", key="a/01", ok=False, detail='[{"id":"f"}]'))
    assert new.lanes[0].tickets[0].status == "changes"
    assert new.phase == "flash" and new.batch == 0
    assert actions == (Action("load_model", model=FLASH),)


def test_AC5_nothing_left_goes_to_pr():
    lane = Lane("a", (TicketState("a/01", 0, status="approved", sha="aa11"),), busy=True)
    s = _state((lane,), phase="review", model=REVIEW)
    new, actions = step(s, Event("reviewed", key="a/01", ok=True))
    assert new.phase == "pr"
    assert actions == (Action("load_model", model=GLM),)


lane_cfg_st = st.lists(
    st.lists(st.tuples(st.integers(0, 1)), min_size=1, max_size=3),
    min_size=1, max_size=2,
)


class CoreReviewMachine(RuleBasedStateMachine):
    """Differential across flash and review: implements drive flash, reviews drive review."""

    @initialize(cfg=lane_cfg_st)
    def build(self, cfg):
        lanes = tuple(
            Lane(f"repo{i}", tuple(TicketState(f"repo{i}/{j + 1:02d}", b) for j, (b,) in enumerate(specs)))
            for i, specs in enumerate(cfg)
        )
        self.state = _state(lanes)
        self.ref = json.loads(json.dumps(to_json(self.state)))

    def _apply(self, ev_json: dict):
        ev = Event(**ev_json)
        new, actions = step(self.state, ev)
        ref_new, ref_actions = ref_step(copy.deepcopy(self.ref), ev_json)
        assert _norm(new) == ref_new, (ev_json, _norm(new), ref_new)
        assert _actions_json(actions) == ref_actions, (ev_json, _actions_json(actions), ref_actions)
        for a in actions:
            if a.kind == "review":
                assert a.model == REVIEW
        self.state = new
        self.ref = ref_new

    @rule()
    def start(self):
        self._apply({"kind": "start", "key": "", "ok": True, "sha": "", "detail": ""})

    @rule(data=st.data())
    def model_ready(self, data):
        phase_model = PHASE_MODEL[self.state.phase] or ""
        detail = data.draw(st.sampled_from((phase_model, "wrong-model", "")))
        self._apply({"kind": "model_ready", "key": "", "ok": True, "sha": "", "detail": detail})

    @rule(data=st.data())
    def implemented(self, data):
        running = [t.key for lane in self.state.lanes for t in lane.tickets if t.status == "running"]
        if not running:
            return
        key = data.draw(st.sampled_from(running))
        self._apply({"kind": "implemented", "key": key, "ok": True, "sha": "abc12345", "detail": ""})

    @rule(data=st.data())
    def reviewed(self, data):
        if self.state.phase != "review":
            return
        running = [t.key for lane in self.state.lanes for t in lane.tickets if t.status == "running"]
        if not running:
            return
        key = data.draw(st.sampled_from(running))
        ok = data.draw(st.booleans())
        self._apply({"kind": "reviewed", "key": key, "ok": ok, "sha": "",
                     "detail": "[]" if ok else '[{"id": "f1"}]'})


TestCoreReview = CoreReviewMachine.TestCase
TestCoreReview.settings = settings(max_examples=40, stateful_step_count=10, deadline=None)
