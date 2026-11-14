"""Core step for the flash and review phases: load the phase model, dispatch work.

`step` is a pure function: it takes a State and an Event and returns a new State
plus the Actions the orchestrator must run. Every change goes through
`dataclasses.replace`, so no input is mutated.
"""

from __future__ import annotations

from dataclasses import replace

from .types import PHASE_MODEL, Action, Event, Lane, NeedsYou, State, TicketState

REVIEWABLE_STATUSES = ("implemented", "fixed")


def ready_tickets(state: State, lane: Lane) -> list[TicketState]:
    """Tickets this lane may take now: status pending, batch within state.batch."""
    return [
        ticket
        for ticket in lane.tickets
        if ticket.status == "pending" and ticket.batch <= state.batch
    ]


def reviewable_tickets(lane: Lane) -> list[TicketState]:
    """Tickets this lane may send to review now: status implemented or fixed."""
    return [t for t in lane.tickets if t.status in REVIEWABLE_STATUSES]


def fixable_tickets(lane: Lane) -> list[TicketState]:
    """Tickets this lane must fix first: status changes, rejected by review."""
    return [t for t in lane.tickets if t.status == "changes"]


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

    if event.kind == "fixed" and event.ok:
        return _dispatch(_mark_fixed(state, event))

    if event.kind == "reviewed":
        marked = _mark_reviewed(state, event)
        if marked is None:
            return state, ()
        return _dispatch(marked)

    return state, ()


def _dispatch(state: State) -> tuple[State, tuple[Action, ...]]:
    """Give one ticket to every idle lane, then end the phase if nothing is left."""
    if state.phase == "review":
        return _dispatch_review(state)
    if state.phase != "flash":
        return state, ()

    actions: list[Action] = []
    lanes: list[Lane] = []

    for lane in state.lanes:
        if lane.busy:
            lanes.append(lane)
            continue
        fix = next((t for t in lane.tickets if t.status == "changes"), None)
        ready = ready_tickets(state, lane)
        if fix is None and not ready:
            lanes.append(lane)
            continue
        # A rejected ticket gets its one fix before any new implement in this lane.
        ticket = fix if fix is not None else ready[0]
        # The action names the phase model, not state.model: a wrong-model
        # model_ready event clears state.model while the phase still runs.
        if fix is not None:
            actions.append(
                Action(
                    "fix",
                    key=ticket.key,
                    model=PHASE_MODEL[state.phase],
                    detail=ticket.findings,
                )
            )
        else:
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
    work = any(
        ready_tickets(state, lane) or fixable_tickets(lane) for lane in state.lanes)
    if not busy and not work:
        review_model = PHASE_MODEL["review"]
        return replace(state, phase="review", model=""), (
            Action("load_model", model=review_model),
        )

    return state, tuple(actions)


def _dispatch_review(state: State) -> tuple[State, tuple[Action, ...]]:
    """Give one reviewable ticket to every idle lane, then leave the phase if done."""
    actions: list[Action] = []
    lanes: list[Lane] = []

    for lane in state.lanes:
        ready = [] if lane.busy else reviewable_tickets(lane)
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
                model=PHASE_MODEL["review"],
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
    work = any(reviewable_tickets(lane) for lane in state.lanes)
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
    if not changes and not next_batch_pending:
        return replace(state, phase="pr", model=""), (
            Action("load_model", model=PHASE_MODEL["pr"]),
        )

    current_open = any(
        ticket.status in ("pending", "running") and ticket.batch == state.batch
        for lane in state.lanes
        for ticket in lane.tickets
    )
    batch = state.batch if current_open else state.batch + 1
    return replace(state, phase="flash", batch=batch, model=""), (
        Action("load_model", model=PHASE_MODEL["flash"]),
    )


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
