"""Ticket title in the status document and schema (multi-project ticket 10)."""
import json
import pathlib

from hypothesis import given, strategies as st

from watcher.status import status_doc
from watcher.types import Lane, State, TicketState

SCHEMA = json.loads((pathlib.Path(__file__).resolve().parent.parent / "schema" / "status-v1.json").read_text())


def _ticket_schema(node):
    if isinstance(node, dict):
        if node.get("required") and "fix_rounds" in node["required"]:
            return node
        for v in node.values():
            found = _ticket_schema(v)
            if found:
                return found
    if isinstance(node, list):
        for v in node:
            found = _ticket_schema(v)
            if found:
                return found
    return None


def _doc(title, status="pending"):
    s = State(prd="p", lanes=(Lane("r", (TicketState("r/01", 0, status=status, title=title),)),))
    return status_doc(s)["lanes"][0]["tickets"][0]


def test_AC1_title_in_status():
    assert _doc("prds-command")["title"] == "prds-command"


def test_AC2_empty_title():
    assert _doc("")["title"] == ""


def test_AC3_schema_has_optional_title():
    t = _ticket_schema(SCHEMA)
    assert "title" in t["properties"] and "title" not in t["required"]


@given(st.text(max_size=20), st.text(min_size=1, max_size=10))
def test_AC4_entry_keys_are_schema_properties(title, status):
    assert set(_doc(title, status)) <= set(_ticket_schema(SCHEMA)["properties"])
