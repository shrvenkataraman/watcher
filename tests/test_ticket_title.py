"""Ticket title in the state (multi-project ticket 09)."""
import json

from hypothesis import given, strategies as st

from watcher.inbox import _title, load_inbox
from watcher.types import Lane, State, TicketState, state_from_json, to_json


def test_AC1_title_from_numbered_file():
    assert _title("/x/03-prds-command.md") == "prds-command"


def test_AC2_title_keeps_inner_dashes_and_plain_stems():
    assert _title("/x/12-a-b-c.md") == "a-b-c"
    assert _title("/x/notes.md") == "notes"


def test_AC3_load_inbox_sets_titles(tmp_path):
    (tmp_path / "spec.md").write_text("# s\n")
    (tmp_path / "manifest.json").write_text(json.dumps(
        {"prd": "demo", "base": "develop", "repos": {"r": {"spec": "spec.md"}}}))
    d = tmp_path / "tickets" / "r"
    d.mkdir(parents=True)
    (d / "01-first-thing.md").write_text("# 01: x\nEdit: a.py\nTest: t.py\nCheck: true\n")
    plan = load_inbox(str(tmp_path))
    assert [t.title for t in plan.state.lanes[0].tickets] == ["first-thing"]


def test_AC4_title_round_trips_and_old_state_loads():
    s = State(prd="p", lanes=(Lane("r", (TicketState("r/01", 0, title="first-thing"),)),))
    assert state_from_json(to_json(s)).lanes[0].tickets[0].title == "first-thing"
    d = to_json(s)
    del d["lanes"][0]["tickets"][0]["title"]
    assert state_from_json(d).lanes[0].tickets[0].title == ""


@given(st.from_regex(r"[0-9]{1,3}", fullmatch=True), st.from_regex(r"[a-z][a-z0-9-]{0,12}", fullmatch=True))
def test_AC1_property_title_after_number(nn, text):
    assert _title(f"/x/{nn}-{text}.md") == text
