"""Core step: model load and implement dispatch, differential against the dict reference (watcher ticket 04)."""
import copy
import json

from hypothesis import settings
from hypothesis import strategies as st
from hypothesis.stateful import RuleBasedStateMachine, initialize, rule

from tests.ref.model import PHASE_MODEL, ref_step
from watcher.core import ready_tickets, step
from watcher.types import Action, Event, Lane, State, TicketState, to_json

FLASH = "qwen3.8-flash-next"


def _norm(obj) -> dict:
    """Compare dataclasses and dicts through their JSON form."""
    return json.loads(json.dumps(to_json(obj) if hasattr(obj, "__dataclass_fields__") else obj))


def _tickets(*specs) -> tuple:
    return tuple(TicketState(key=k, batch=b) for k, b in specs)


def _state(lanes, batch=0, phase="flash", model="", prd="demo") -> State:
    return State(prd=prd, phase=phase, batch=batch, model=model, lanes=lanes)


def _ref(state: State) -> dict:
    return json.loads(json.dumps(to_json(state)))


def _actions_json(actions) -> list:
    return [json.loads(json.dumps(to_json(a))) for a in actions]


def test_AC1_start_emits_exactly_one_load_model_for_the_flash_model():
    s = _state((Lane("quark-kit", _tickets(("quark-kit/01", 0))),))
    new, actions = step(s, Event("start"))
    assert actions == (Action("load_model", model=FLASH),)
    assert new.model == ""


def test_AC2_model_ready_dispatches_one_implement_per_idle_lane():
    s = _state((Lane("quark-kit", _tickets(("quark-kit/01", 0), ("quark-kit/02", 0))),
                Lane("qresearch", _tickets(("qresearch/01", 0),))))
    new, actions = step(s, Event("model_ready", detail=FLASH))
    assert [a.key for a in actions] == ["quark-kit/01", "qresearch/01"]
    assert all(a.kind == "implement" and a.model == FLASH for a in actions)
    assert all(lane.busy for lane in new.lanes)
    assert new.model == FLASH and new.load_tries == 0


def test_AC2_wrong_model_reloads_instead_of_dispatching():
    s = _state((Lane("quark-kit", _tickets(("quark-kit/01", 0))),))
    new, actions = step(s, Event("model_ready", detail="qwen3.8-27b-w8a8"))
    assert actions == (Action("load_model", model=FLASH),)
    assert new.model == ""


def test_AC3_implemented_frees_the_lane_and_dispatches_the_next_batch0_ticket():
    tickets = (TicketState("quark-kit/01", 0, status="running"), TicketState("quark-kit/02", 0))
    s = _state((Lane("quark-kit", tickets, busy=True),), model=FLASH)
    new, actions = step(s, Event("implemented", key="quark-kit/01", ok=True, sha="abc12345"))
    first = new.lanes[0].tickets[0]
    assert first.status == "implemented" and first.sha == "abc12345"
    assert actions == (Action("implement", key="quark-kit/02", model=FLASH),)
    assert new.lanes[0].busy is True


def test_AC3_implemented_frees_lane_when_no_work_left():
    running = (TicketState("quark-kit/01", 0, status="running"),)
    s = _state((Lane("quark-kit", running, busy=True),), model=FLASH)
    new, actions = step(s, Event("implemented", key="quark-kit/01", ok=True, sha="abc12345"))
    assert new.lanes[0].busy is False
    assert new.phase == "review"
    assert actions == (Action("load_model", model="qwen3.8-27b-w8a8"),)


def test_AC4_last_batch0_implemented_ends_the_phase_with_one_review_load():
    lane1 = Lane("quark-kit", (TicketState("quark-kit/01", 0, status="running"),), busy=True)
    lane2 = Lane("qresearch", (TicketState("qresearch/01", 0, status="implemented", sha="beef123"),))
    s = _state((lane1, lane2), model=FLASH)
    new, actions = step(s, Event("implemented", key="quark-kit/01", ok=True, sha="cafe0123"))
    assert new.phase == "review" and new.model == ""
    assert actions == (Action("load_model", model="qwen3.8-27b-w8a8"),)


def test_AC5_tickets_beyond_the_current_batch_are_never_dispatched():
    lane = Lane("quark-kit", _tickets(("quark-kit/01", 1)))
    s = _state((lane,), batch=0)
    _, actions = step(s, Event("model_ready", detail=FLASH))
    assert all(a.key != "quark-kit/01" for a in actions if a.kind == "implement")


def test_unknown_event_kind_is_a_no_op():
    s = _state((Lane("quark-kit", _tickets(("quark-kit/01", 0))),))
    new, actions = step(s, Event("question", key="quark-kit/01"))
    assert new == s and actions == ()


def test_ready_tickets_filters_by_status_and_batch():
    s = _state((Lane("quark-kit", _tickets(("quark-kit/01", 0), ("quark-kit/02", 1))),), batch=0)
    got = ready_tickets(s, s.lanes[0])
    assert [t.key for t in got] == ["quark-kit/01"]


lane_cfg_st = st.lists(
    st.lists(st.tuples(st.integers(0, 1)), min_size=1, max_size=3),
    min_size=1, max_size=3,
)


class CoreImplementMachine(RuleBasedStateMachine):
    """Differential: step() against ref_step() over random lanes and event sequences."""

    @initialize(cfg=lane_cfg_st)
    def build(self, cfg):
        lanes = tuple(
            Lane(f"repo{i}", tuple(TicketState(f"repo{i}/{j + 1:02d}", b) for j, (b,) in enumerate(specs)))
            for i, specs in enumerate(cfg)
        )
        self.state = _state(lanes)
        self.ref = _ref(self.state)

    def _apply(self, ev_json: dict):
        ev = Event(**ev_json)
        new, actions = step(self.state, ev)
        ref_new, ref_actions = ref_step(copy.deepcopy(self.ref), ev_json)
        assert _norm(new) == ref_new, (ev_json, _norm(new), ref_new)
        assert _actions_json(actions) == ref_actions, (ev_json, _actions_json(actions), ref_actions)
        for a in actions:
            if a.kind == "implement":
                batch = next(t.batch for lane in new.lanes for t in lane.tickets if t.key == a.key)
                assert batch <= new.batch
        self.state = new
        self.ref = ref_new

    @rule()
    def start(self):
        self._apply({"kind": "start", "key": "", "ok": True, "sha": "", "detail": ""})

    @rule(data=st.data())
    def model_ready(self, data):
        detail = data.draw(st.sampled_from((FLASH, "qwen3.8-27b-w8a8", "")))
        self._apply({"kind": "model_ready", "key": "", "ok": True, "sha": "", "detail": detail})

    @rule(data=st.data())
    def implemented(self, data):
        running = [t.key for lane in self.state.lanes for t in lane.tickets if t.status == "running"]
        if not running:
            return
        key = data.draw(st.sampled_from(running))
        self._apply({"kind": "implemented", "key": key, "ok": True, "sha": "abc12345", "detail": ""})


TestCoreImplement = CoreImplementMachine.TestCase
TestCoreImplement.settings = settings(max_examples=30, stateful_step_count=8, deadline=None)
