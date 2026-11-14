"""Regenerate status.json from the real producer. Run from repo root:
uv run python kanban/tests/fixtures/make_status.py"""
import json
import pathlib

from watcher.status import status_doc
from watcher.types import TICKET_STATUSES, Lane, NeedsYou, State, TicketState

shas = {"implemented": "a1b2c3d", "approved": "e4f5a6b", "fixed": "c7d8e9f", "changes": "0123abc"}
tickets = [TicketState(key=f"T{i}", batch=1, status=s, sha=shas.get(s, ""))
           for i, s in enumerate(TICKET_STATUSES, 1)]
state = State(
    prd="prd-demo", phase="review", batch=2, model="qwen3.8-27b-w8a8",
    lanes=(Lane(repo="alpha", tickets=tuple(tickets[:4]), pr_status="none"),
           Lane(repo="beta", tickets=tuple(tickets[4:]), pr_status="open")),
    needs_you=(NeedsYou(key="T7", reason="blocked", detail="needs a human"),),
)
out = pathlib.Path(__file__).with_name("status.json")
out.write_text(json.dumps(status_doc(state), indent=2) + "\n")
