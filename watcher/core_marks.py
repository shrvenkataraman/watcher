"""Decide what a review, fix or implement result does to a ticket."""
from __future__ import annotations

from dataclasses import replace

from .types import Event, Lane, NeedsYou, State

def _mark_reviewed(state: State, event: Event) -> State | None:
    """Record a review verdict: lane free, ticket approved, changes or needs_you.

    Returns None when no running ticket carries the key, so `step` emits nothing.
    A rejection that already used its one fix round waits for a human (ticket 07).
    """
    lane_index: int | None = None
    for index, lane in enumerate(state.lanes):
        if any(ticket.key == event.key for ticket in lane.tickets):
            lane_index = index
    if lane_index is None:
        return None

    lane = state.lanes[lane_index]
    ticket = next(t for t in lane.tickets if t.key == event.key)
    if ticket.status == "approved":
        return replace(state, lanes=tuple(
            replace(l, busy=False) if i == lane_index else l
            for i, l in enumerate(state.lanes)))
    entry: tuple[NeedsYou, ...] = ()
    if event.ok:
        updated = replace(ticket, status="approved")
    elif ticket.fix_rounds >= 1:
        updated = replace(ticket, status="needs_you")
        entry = (NeedsYou(ticket.key, "review_rejected_twice", event.detail),)
    else:
        updated = replace(ticket, status="changes", findings=event.detail)

    lanes = list(state.lanes)
    lanes[lane_index] = replace(
        lane,
        busy=False,
        tickets=tuple(
            updated if other.key == ticket.key else other for other in lane.tickets
        ),
    )
    return replace(state, lanes=tuple(lanes), needs_you=state.needs_you + entry)


def _mark_fixed(state: State, event: Event) -> State:
    """Record a fix result: ticket fixed with its sha, one round spent, lane free."""
    lanes: list[Lane] = []
    for lane in state.lanes:
        if not any(ticket.key == event.key for ticket in lane.tickets):
            lanes.append(lane)
            continue
        lanes.append(
            replace(
                lane,
                busy=False,
                tickets=tuple(
                    replace(
                        ticket,
                        status="fixed",
                        sha=event.sha,
                        fix_rounds=ticket.fix_rounds + 1,
                    )
                    if ticket.key == event.key
                    else ticket
                    for ticket in lane.tickets
                ),
            )
        )
    return replace(state, lanes=tuple(lanes))


def _mark_implemented(state: State, event: Event) -> State:
    """Record an implement result: ticket implemented with its sha, lane free."""
    lanes: list[Lane] = []
    for lane in state.lanes:
        if not any(ticket.key == event.key for ticket in lane.tickets):
            lanes.append(lane)
            continue
        lanes.append(
            replace(
                lane,
                busy=False,
                tickets=tuple(
                    replace(ticket, status="implemented", sha=event.sha)
                    if ticket.key == event.key
                    else ticket
                    for ticket in lane.tickets
                ),
            )
        )
    return replace(state, lanes=tuple(lanes))
