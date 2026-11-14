"""Decide when the review phase ends and which phase comes next."""
from __future__ import annotations

from dataclasses import replace

from watcher import core as _core
from .types import Action, Lane, State

def _dispatch_review(state: State) -> tuple[State, tuple[Action, ...]]:
    """Give one reviewable ticket to every idle lane, then leave the phase if done."""
    actions: list[Action] = []
    lanes: list[Lane] = []

    for lane in state.lanes:
        ready = [] if lane.busy else _core.reviewable_tickets(lane)
        if not ready:
            lanes.append(lane)
            continue
        ticket = ready[0]
        # detail="fixed" remembers the prior status: ticket 06 reads it to tell a
        # first review from a review of a fix.
        actions.append(
            Action(
                "review",
                key=ticket.key,
                model=_core.model_for(state, "review"),
                detail="fixed" if ticket.status == "fixed" else "",
            )
        )
        lanes.append(
            replace(
                lane,
                busy=True,
                tickets=tuple(
                    replace(other, status="running")
                    if other.key == ticket.key
                    else other
                    for other in lane.tickets
                ),
            )
        )

    state = replace(state, lanes=tuple(lanes))

    busy = any(lane.busy for lane in state.lanes)
    work = any(_core.reviewable_tickets(lane) for lane in state.lanes)
    if not busy and not work:
        return _next_phase(state)

    return state, tuple(actions)


def _next_phase(state: State) -> tuple[State, tuple[Action, ...]]:
    """Leave review: back to flash while work remains, otherwise to pr."""
    changes = any(
        ticket.status == "changes"
        for lane in state.lanes
        for ticket in lane.tickets
    )
    next_batch_pending = any(
        ticket.status == "pending" and ticket.batch == state.batch + 1
        for lane in state.lanes
        for ticket in lane.tickets
    )
    ready_now = any(_core.ready_tickets(state, lane) for lane in state.lanes)
    if not changes and not next_batch_pending and not ready_now:
        if _core.waiting_on_human(state):
            # A pending ticket waits on a needs_you dependency. Leaving review for
            # pr would end the run while that ticket can never run, so stay here.
            return state, ()
        return replace(state, phase="pr", model=""), (
            Action("load_model", model=_core.model_for(state, "pr")),
        )

    current_open = any(
        ticket.status in ("pending", "running") and ticket.batch == state.batch
        for lane in state.lanes
        for ticket in lane.tickets
    )
    batch = state.batch if current_open else state.batch + 1
    return replace(state, phase="flash", batch=batch, model=""), (
        Action("load_model", model=_core.model_for(state, "flash")),
    )
