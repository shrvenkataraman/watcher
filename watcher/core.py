"""Core step for the flash phase: load the phase model, dispatch implement work.

`step` is a pure function: it takes a State and an Event and returns a new State
plus the Actions the orchestrator must run. Every change goes through
`dataclasses.replace`, so no input is mutated.
"""

from __future__ import annotations

from dataclasses import replace

from .types import PHASE_MODEL, Action, Event, Lane, State, TicketState


def ready_tickets(state: State, lane: Lane) -> list[TicketState]:
    """Tickets this lane may take now: status pending, batch within state.batch."""
    return [
        ticket
        for ticket in lane.tickets
        if ticket.status == "pending" and ticket.batch <= state.batch
    ]


def step(state: State, event: Event) -> tuple[State, tuple[Action, ...]]:
    """Return the next state and the actions for one event."""
    wanted = PHASE_MODEL.get(state.phase)

    if event.kind in ("start", "model_ready"):
        # `start` asks for the phase model, so it compares against the loaded model.
        # `model_ready` reports a loaded model, so it compares against event.detail.
        have = state.model if event.kind == "start" else event.detail
        if have != wanted:
            return replace(state, model=""), (Action("load_model", model=wanted),)
        return _dispatch(replace(state, model=wanted, load_tries=0))

    if event.kind == "implemented" and event.ok:
        return _dispatch(_mark_implemented(state, event))

    return state, ()


def _dispatch(state: State) -> tuple[State, tuple[Action, ...]]:
    """Give one ticket to every idle lane, then end the phase if nothing is left."""
    if state.phase != "flash":
        return state, ()

    actions: list[Action] = []
    lanes: list[Lane] = []

    for lane in state.lanes:
        ready = [] if lane.busy else ready_tickets(state, lane)
        if not ready:
            lanes.append(lane)
            continue
        ticket = ready[0]
        # The action names the phase model, not state.model: a wrong-model
        # model_ready event clears state.model while the phase still runs.
        actions.append(
            Action("implement", key=ticket.key, model=PHASE_MODEL[state.phase])
        )
        lanes.append(
            replace(
                lane,
                busy=True,
                tickets=tuple(
                    replace(ticket, status="running")
                    if other.key == ticket.key
                    else other
                    for other in lane.tickets
                ),
            )
        )

    state = replace(state, lanes=tuple(lanes))

    busy = any(lane.busy for lane in state.lanes)
    work = any(ready_tickets(state, lane) for lane in state.lanes)
    if not busy and not work:
        review_model = PHASE_MODEL["review"]
        return replace(state, phase="review", model=""), (
            Action("load_model", model=review_model),
        )

    return state, tuple(actions)


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
