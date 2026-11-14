"""State.models overrides: core reads models through State, metamorphic against no overrides (ticket 06)."""
import json
import subprocess
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from tests.ref.model import PHASE_MODEL
from watcher.core import step
from watcher.types import Event, Lane, State, TicketState, state_from_json, to_json

OVERRIDE = (("flash", "f"), ("review", "r"), ("pr", "p"))
CORE = Path(__file__).resolve().parent.parent / "watcher" / "core.py"


def _base(models=()) -> State:
    lanes = (Lane("qk", (TicketState("qk/01", 0), TicketState("qk/02", 0))),
             Lane("qr", (TicketState("qr/01", 0),)))
    return State(prd="demo", lanes=lanes, models=models)


def _replay(models, names):
    """Replay a fixed script. model_ready names the model the state wants, mapped by `names`."""
    s = _base(models)
    out = []
    s, acts = step(s, Event("start"))
    out.append((s, acts))
    s, acts = step(s, Event("model_ready", detail=names["flash"]))
    out.append((s, acts))
    for a in acts:
        if a.kind == "implement":
            s, acts2 = step(s, Event("implemented", key=a.key, ok=True, sha="aa1"))
            out.append((s, acts2))
    return out


def _phase_of(model, names):
    inv = {v: k for k, v in names.items()}
    return inv.get(model, model)


def _norm(pairs, names):
    res = []
    for s, acts in pairs:
        d = json.loads(json.dumps(to_json(s)))
        d["model"] = _phase_of(d["model"], names)
        d.pop("models", None)
        al = []
        for a in acts:
            ad = json.loads(json.dumps(to_json(a)))
            ad["model"] = _phase_of(ad["model"], names)
            al.append(ad)
        res.append((d, al))
    return res


def test_AC1_empty_models_default_and_uses_phase_model():
    assert State(prd="x").models == ()
    s, acts = step(_base(), Event("start"))
    assert acts[0].kind == "load_model" and acts[0].model == PHASE_MODEL["flash"]


def test_AC2_start_loads_override_and_implement_carries_it():
    s, acts = step(_base(OVERRIDE), Event("start"))
    assert [(a.kind, a.model) for a in acts] == [("load_model", "f")]
    s, acts = step(s, Event("model_ready", detail="f"))
    impl = [a for a in acts if a.kind == "implement"]
    assert impl and all(a.model == "f" for a in impl)


name = st.text(min_size=1, max_size=8).filter(lambda t: t not in PHASE_MODEL.values())


@settings(max_examples=40, deadline=None)
@given(f=name, r=name, p=name)
def test_AC2_property_overrides_change_only_model_fields(f, r, p):
    if len({f, r, p}) < 3:
        return
    names = {"flash": f, "review": r, "pr": p}
    over = _replay(tuple(names.items()), names)
    plain = _replay((), dict(PHASE_MODEL))
    assert _norm(over, names) == _norm(plain, dict(PHASE_MODEL))
    assert any(a.model == f for _, acts in over for a in acts)


def test_AC3_json_round_trip_with_models():
    s = _base(OVERRIDE)
    data = json.loads(json.dumps(to_json(s)))
    assert data["models"] == [list(p) for p in OVERRIDE]
    assert state_from_json(data) == s


@settings(max_examples=40, deadline=None)
@given(models=st.lists(st.tuples(st.text(max_size=6), st.text(max_size=6)), max_size=4).map(tuple))
def test_AC3_property_round_trip(models):
    s = _base(models)
    assert state_from_json(json.loads(json.dumps(to_json(s)))) == s


def test_AC4_core_mentions_phase_model_at_most_twice():
    assert sum("PHASE_MODEL" in ln for ln in CORE.read_text().splitlines()) <= 2
