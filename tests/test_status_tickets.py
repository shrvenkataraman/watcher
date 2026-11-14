"""Status JSON lists every ticket per lane (watcher ticket 18)."""
import json

from hypothesis import given, settings
import hypothesis.strategies as st

from watcher.status import status_doc
from watcher.types import Lane, State, TicketState, TICKET_STATUSES

_key = st.text(alphabet="abcdefgh0123456789/", min_size=1, max_size=8)
_ticket = st.builds(
    TicketState, key=_key, batch=st.integers(0, 3),
    depends_on=st.lists(_key, max_size=3).map(tuple),
    status=st.sampled_from(TICKET_STATUSES), sha=st.text(max_size=6),
    verify_fails=st.integers(0, 5), fix_rounds=st.integers(0, 5))
_lane = st.builds(Lane, repo=_key, tickets=st.lists(_ticket, max_size=5).map(tuple))
_state = st.builds(State, prd=st.just("p"), lanes=st.lists(_lane, max_size=3).map(tuple))


def test_AC1_lane_lists_tickets_in_order():
    t1 = TicketState("r/01", 0, status="approved", sha="abc")
    t2 = TicketState("r/02", 0, depends_on=("r/01",))
    doc = status_doc(State(prd="p", lanes=(Lane("r", (t1, t2)),)))
    assert doc["lanes"][0]["tickets"] == [
        {"key": "r/01", "status": "approved", "sha": "abc", "depends_on": [],
         "verify_fails": 0, "fix_rounds": 0},
        {"key": "r/02", "status": "pending", "sha": "", "depends_on": ["r/01"],
         "verify_fails": 0, "fix_rounds": 0},
    ]


@settings(max_examples=50)
@given(_state)
def test_AC1_property_keys_and_statuses_match_state(state):
    doc = status_doc(state)
    got = [(t["key"], t["status"]) for lane in doc["lanes"] for t in lane["tickets"]]
    want = [(t.key, t.status) for lane in state.lanes for t in lane.tickets]
    assert got == want


def test_AC2_schema_stays_1():
    assert status_doc(State(prd="p"))["schema"] == 1


@settings(max_examples=50)
@given(_state)
def test_AC3_property_json_dumps_succeeds_with_lists(state):
    doc = status_doc(state)
    json.dumps(doc)
    for lane in doc["lanes"]:
        assert isinstance(lane["tickets"], list)
        assert all(isinstance(t["depends_on"], list) for t in lane["tickets"])
