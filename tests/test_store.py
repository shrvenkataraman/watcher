"""Atomic state file and JSONL event log (watcher ticket 03)."""
import json
import os

import pytest
from hypothesis import given, settings, HealthCheck
import hypothesis.strategies as st

from watcher.store import append_event, load, read_events, save, state_dir
from watcher.types import Event, Lane, NeedsYou, State, TicketState, to_json

state_st = st.builds(
    State,
    prd=st.text(min_size=1, max_size=8, alphabet="abcdefgh"),
    phase=st.sampled_from(("flash", "review", "pr", "done")),
    batch=st.integers(0, 2),
    model=st.sampled_from(("", "qwen3.8-flash-next")),
    lanes=st.just((Lane("quark-kit", (TicketState("quark-kit/01", 0),)),)),
    needs_you=st.lists(st.builds(NeedsYou, key=st.just("quark-kit/02"), reason=st.just("question")),
                       max_size=2).map(tuple),
    load_tries=st.integers(0, 1),
)


def _fixture() -> State:
    return State(prd="demo", phase="flash", batch=0, model="qwen3.8-flash-next",
                 lanes=(Lane("quark-kit", (TicketState("quark-kit/01", 0),
                                           TicketState("quark-kit/02", 0, status="approved", sha="abc1234")),),),
                 needs_you=(NeedsYou("quark-kit/03", "verify_failed_twice", "tail"),), load_tries=1)


def test_AC1_round_trip_through_the_file(tmp_path):
    s = _fixture()
    save(s, root=str(tmp_path))
    assert load(s.prd, root=str(tmp_path)) == s


@settings(deadline=None, max_examples=25, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(state_st)
def test_AC1_property_round_trip_for_generated_states(tmp_path, s):
    root = str(tmp_path / s.prd)
    save(s, root=root)
    assert load(s.prd, root=root) == s


def test_AC2_failed_replace_leaves_previous_state_whole(tmp_path, monkeypatch):
    s = _fixture()
    save(s, root=str(tmp_path))

    def boom(src, dst):
        raise OSError("simulated crash before rename")

    monkeypatch.setattr(os, "replace", boom)
    changed = State(prd=s.prd, phase="review")
    with pytest.raises(OSError):
        save(changed, root=str(tmp_path))
    assert load(s.prd, root=str(tmp_path)) == s


def test_AC3_unknown_prd_loads_none(tmp_path):
    assert load("never-saved", root=str(tmp_path)) is None


def test_AC4_events_append_in_order_and_a_truncated_tail_is_skipped(tmp_path):
    prd = "demo"
    events = [Event("implemented", key=f"quark-kit/{i:02d}", sha=f"sha{i}") for i in range(3)]
    for e in events:
        append_event(prd, e, root=str(tmp_path))
    assert read_events(prd, root=str(tmp_path)) == events

    path = os.path.join(state_dir(prd, root=str(tmp_path)), "events.jsonl")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write('{"kind": "imp')  # torn final line, no newline

    assert read_events(prd, root=str(tmp_path)) == events


def test_AC4_property_read_events_after_n_appends(tmp_path):
    prd = "gen"
    made = [Event("model_ready", detail=f"m{i}") for i in range(5)]
    for e in made:
        append_event(prd, e, root=str(tmp_path))
    assert read_events(prd, root=str(tmp_path)) == made


def test_state_dir_uses_root_watcher_prd(tmp_path):
    assert state_dir("demo", root=str(tmp_path)) == os.path.join(str(tmp_path), "watcher", "demo")


def test_save_writes_readable_json(tmp_path):
    s = _fixture()
    save(s, root=str(tmp_path))
    with open(os.path.join(state_dir(s.prd, root=str(tmp_path)), "state.json"), encoding="utf-8") as fh:
        assert json.load(fh) == to_json(s)
