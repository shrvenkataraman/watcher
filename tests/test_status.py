"""Status document + text render, validated against the JSON Schema (watcher ticket 18)."""
import json
import os

import pytest
from hypothesis import given, settings
import hypothesis.strategies as st

from watcher.status import SCHEMA_VERSION, render_text, status_doc
from watcher.types import Lane, NeedsYou, State, TicketState, TICKET_STATUSES

SCHEMA_PATH = os.path.join(os.path.dirname(__file__), "..", "schema", "status-v1.json")

DETAIL = "which base branch should I use for the retry?"


def _fixture_state() -> State:
    qk = Lane("quark-kit", (
        TicketState("quark-kit/01", 0, status="approved", sha="a1"),
        TicketState("quark-kit/02", 0, status="running"),
        TicketState("quark-kit/03", 1, status="approved", sha="a3"),
        TicketState("quark-kit/04", 1, status="approved", sha="a4"),
        TicketState("quark-kit/05", 1),
        TicketState("quark-kit/06", 1),
        TicketState("quark-kit/07", 1, status="needs_you"),
    ), busy=True)
    qr = Lane("qresearch", (TicketState("qresearch/01", 0, status="approved", sha="b1"),),
              pr_status="objected: 2 findings")
    return State(prd="demo", phase="review", batch=1, model="qwen3.8-27b-w8a8",
                 lanes=(qk, qr), needs_you=(NeedsYou("quark-kit/07", "question", DETAIL),))


def _validate(instance, schema):
    """Tiny validator for the schema subset used by status-v1.json."""
    t = schema.get("type")
    if t is not None:
        types = t if isinstance(t, list) else [t]
        ok = False
        for tt in types:
            if tt == "object" and isinstance(instance, dict):
                ok = True
            elif tt == "array" and isinstance(instance, list):
                ok = True
            elif tt == "string" and isinstance(instance, str):
                ok = True
            elif tt == "boolean" and isinstance(instance, bool):
                ok = True
            elif tt == "integer" and isinstance(instance, int) and not isinstance(instance, bool):
                ok = True
            elif tt == "null" and instance is None:
                ok = True
        assert ok, (instance, t)
    if isinstance(instance, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            assert req in instance, req
        if schema.get("additionalProperties") is False:
            assert set(instance) <= set(props), set(instance) - set(props)
        for k, v in instance.items():
            if k in props:
                _validate(v, props[k])
    if isinstance(instance, list) and "items" in schema:
        for item in instance:
            _validate(item, schema["items"])
    if "enum" in schema:
        assert instance in schema["enum"], instance


def _schema():
    with open(SCHEMA_PATH) as fh:
        return json.load(fh)


def test_AC1_doc_validates_against_schema():
    doc = status_doc(_fixture_state())
    schema = _schema()
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    _validate(doc, schema)


def test_schema_has_additionalProperties_false_at_every_object_level():
    def walk(s):
        if isinstance(s, dict):
            if s.get("type") == "object":
                assert s.get("additionalProperties") is False
            for v in s.values():
                walk(v)
        elif isinstance(s, list):
            for v in s:
                walk(v)
    walk(_schema())


def test_AC1_document_shape():
    doc = status_doc(_fixture_state())
    assert doc["schema"] == SCHEMA_VERSION == 1
    assert doc["prd"] == "demo" and doc["phase"] == "review"
    assert doc["batch"] == 1 and doc["model"] == "qwen3.8-27b-w8a8"
    assert doc["needs_you"] == [{"key": "quark-kit/07", "reason": "question", "detail": DETAIL}]
    qk = doc["lanes"][0]
    assert qk["repo"] == "quark-kit" and qk["busy"] is True and qk["pr_status"] == "none"
    assert qk["running"] == "quark-kit/02"
    assert qk["counts"]["pending"] == 2 and qk["counts"]["approved"] == 3
    assert qk["counts"]["needs_you"] == 1 and qk["counts"]["running"] == 1
    qr = doc["lanes"][1]
    assert qr["pr_status"] == "objected"       # "objected: 2 findings" normalises
    assert qr["running"] is None


def test_AC2_counts_sum_to_lane_ticket_count():
    doc = status_doc(_fixture_state())
    state = _fixture_state()
    for lane, lane_doc in zip(state.lanes, doc["lanes"]):
        assert sum(lane_doc["counts"].values()) == len(lane.tickets)
    assert set(doc["lanes"][0]["counts"]) == set(TICKET_STATUSES)


def test_AC3_render_text_golden():
    text = render_text(status_doc(_fixture_state()))
    expected = "\n".join([
        "demo  phase=review  batch=1  model=qwen3.8-27b-w8a8",
        "NEEDS YOU (1)",
        f"  quark-kit/07  question  {DETAIL[:60]}",
        f"  {'quark-kit':<20} 3/7 approved  running=quark-kit/02  pr=none",
        f"  {'qresearch':<20} 1/1 approved  running=-  pr=objected",
    ])
    assert text.strip() == expected.strip()


status_st = st.sampled_from(TICKET_STATUSES)
ticket_st = st.builds(TicketState, key=st.integers(1, 5).map(lambda i: f"a/{i:02d}"),
                      batch=st.integers(0, 1), status=status_st)
state_st = st.builds(
    State,
    prd=st.just("p"), phase=st.sampled_from(("flash", "review", "pr", "done")),
    batch=st.integers(0, 2), model=st.sampled_from(("", "m")),
    lanes=st.just((Lane("a", (TicketState("a/01", 0), TicketState("a/02", 0))),
                   Lane("bb", (TicketState("bb/01", 1, status="approved"),)))),
    needs_you=st.just(()), load_tries=st.just(0),
)


@settings(deadline=None, max_examples=50)
@given(state_st)
def test_properties_schema_valid_and_counts_sum(s):
    doc = status_doc(s)
    _validate(doc, _schema())
    for lane, lane_doc in zip(s.lanes, doc["lanes"]):
        assert sum(lane_doc["counts"].values()) == len(lane.tickets)
