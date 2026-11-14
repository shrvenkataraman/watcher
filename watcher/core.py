"""Core step for the flash and review phases: load the phase model, dispatch work.

`step` is a pure function: it takes a State and an Event and returns a new State
plus the Actions the orchestrator must run. Every change goes through
`dataclasses.replace`, so no input is mutated.
"""

from __future__ import annotations

from dataclasses import replace

from .types import PHASE_MODEL, Action, Event, Lane, NeedsYou, State, TicketState

REVIEWABLE_STATUSES = ("implemented", "fixed")
OBJECTION_PREFIX = "objected:"


def status(state: State, key: str) -> str:
    """Status of the ticket with this key, or "" when no lane carries it."""
    for lane in state.lanes:
        for ticket in lane.tickets:
            if ticket.key == key:
                return ticket.status
    return ""


def ready_tickets(state: State, lane: Lane) -> list[TicketState]:
    """Tickets this lane may take now: pending, batch within state.batch, deps approved."""
    return [
        ticket
        for ticket in lane.tickets
        if ticket.status == "pending"
        and ticket.batch <= state.batch
        and all(status(state, dep) == "approved" for dep in ticket.depends_on)
    ]


def reviewable_tickets(lane: Lane) -> list[TicketState]:
    """Tickets this lane may send to review now: status implemented or fixed."""
    return [t for t in lane.tickets if t.status in REVIEWABLE_STATUSES]


def fixable_tickets(lane: Lane) -> list[TicketState]:
    """Tickets this lane must fix first: status changes, rejected by review."""
    return [t for t in lane.tickets if t.status == "changes"]


def finished(lane: Lane) -> bool:
    """Every ticket of this lane is approved or skipped, so the lane can take a PR."""
    return all(t.status in ("approved", "skipped") for t in lane.tickets)


LOAD_TRIES = 3  # a Flash-Next start can fail while RAM frees up after a swap


def step(state: State, event: Event) -> tuple[State, tuple[Action, ...]]:
    """Return the next state and the actions for one event."""
    wanted = PHASE_MODEL.get(state.phase)

    if event.kind in ("start", "model_ready"):
        # `start` asks for the phase model, so it compares against the loaded model.
        # `model_ready` reports a loaded model, so it compares against event.detail.
        have = state.model if event.kind == "start" else event.detail
        if have != wanted:
            return replace(state, model=""), (Action("load_model", model=wanted),)
        cleared = tuple(n for n in state.needs_you if n.key != "model")
        return _dispatch(replace(state, model=wanted, load_tries=0, needs_you=cleared))

    if event.kind == "implemented" and event.ok:
        return _dispatch(_mark_implemented(state, event))

    if event.kind == "fixed" and event.ok:
        return _dispatch(_mark_fixed(state, event))

    if event.kind == "reviewed":
        marked = _mark_reviewed(state, event)
        if marked is None:
            return state, ()
        return _dispatch(marked)

    if event.kind == "pr_reviewed":
        return _pr_reviewed(state, event)
    if event.kind == "pr_fixed":
        return _pr_fixed(state, event)

    if event.kind in ("implemented", "fixed") and not event.ok:
        return _verify_failed(state, event)
    if event.kind == "question":
        return _park(state, event.key, "question", event.detail)
    if event.kind == "timeout":
        return _park(state, event.key, "stalled")
    if event.kind == "bad_verdict":
        return _park(state, event.key, "bad_verdict")
    if event.kind == "model_failed":
        return _model_failed(state, event)
    if event.kind == "phase_timeout":
        return _park_running(state)
    if event.kind in ("answered", "retry"):
        return _user_release(state, event)
    if event.kind == "skip":
        return _skip(state, event)
    if event.kind == "abort":
        return replace(state, phase="done"), (Action("write_summary"),)

    return state, ()


def _locate(
    state: State, key: str, status: str | None = None
) -> tuple[int, TicketState] | None:
    """First lane index and ticket that carry this key, with this status if given."""
    for i, lane in enumerate(state.lanes):
        for ticket in lane.tickets:
            if ticket.key == key and (status is None or ticket.status == status):
                return i, ticket
    return None


def _place(state: State, i: int, ticket: TicketState, busy: bool = False) -> State:
    """This lane carries `ticket`; the lane goes idle unless `busy`."""
    lanes = list(state.lanes)
    lanes[i] = replace(lanes[i], busy=busy, tickets=tuple(
        ticket if t.key == ticket.key else t for t in lanes[i].tickets))
    return replace(state, lanes=tuple(lanes))


def _drop_needs(state: State, key: str) -> State:
    """Drop every needs_you entry that carries this key."""
    return replace(state, needs_you=tuple(n for n in state.needs_you if n.key != key))


def _lane_by_repo(state: State, repo: str) -> tuple[int, Lane] | None:
    """Index and lane whose repo is this key, or None when no lane carries it."""
    for i, lane in enumerate(state.lanes):
        if lane.repo == repo:
            return i, lane
    return None


def _set_lane(state: State, i: int, lane: Lane) -> State:
    """Swap lane `i` for `lane`, leave every other lane as it was."""
    lanes = list(state.lanes)
    lanes[i] = lane
    return replace(state, lanes=tuple(lanes))


def _park(
    state: State, key: str, reason: str, detail: str = ""
) -> tuple[State, tuple[Action, ...]]:
    """Park a ticket as needs_you, notify once, then dispatch what lanes can take."""
    found = _locate(state, key)
    if found:
        i, ticket = found
        state = _place(state, i, replace(ticket, status="needs_you"))
    state, actions = _dispatch(replace(
        state, needs_you=state.needs_you + (NeedsYou(key, reason, detail),)))
    return state, (Action("notify", key=key, detail=f"{reason}: {key}"),) + actions


def _verify_failed(
    state: State, event: Event
) -> tuple[State, tuple[Action, ...]]:
    """First verify failure retries with the failure tail, the second parks it."""
    found = _locate(state, event.key, "running")
    if not found:
        return state, ()
    i, ticket = found
    failed = replace(ticket, verify_fails=ticket.verify_fails + 1)
    if failed.verify_fails > 1:
        return _park(_place(state, i, failed), event.key, "verify_failed_twice")
    retried = replace(failed, status="changes" if failed.findings else "pending")
    state, actions = _dispatch(_place(state, i, retried))
    return state, tuple(
        replace(a, detail=event.detail) if a.key == event.key else a for a in actions)


def _model_failed(
    state: State, event: Event
) -> tuple[State, tuple[Action, ...]]:
    """Retry a model load twice, then park `model` for a human."""
    state = replace(state, load_tries=state.load_tries + 1)
    if state.load_tries < LOAD_TRIES:
        return state, (Action("load_model", model=PHASE_MODEL.get(state.phase)),)
    entry = NeedsYou("model", "model_failed", event.detail)
    return replace(state, needs_you=state.needs_you + (entry,)), (
        Action("notify", key=entry.key, detail=f"{entry.reason}: {entry.key}"),)


def _park_running(state: State) -> tuple[State, tuple[Action, ...]]:
    """Park every still-running ticket as stalled."""
    actions: list[Action] = []
    for lane in state.lanes:
        for ticket in lane.tickets:
            if ticket.status == "running":
                state, parked = _park(state, ticket.key, "stalled")
                actions.extend(parked)
    return state, tuple(actions)


def _user_release(
    state: State, event: Event
) -> tuple[State, tuple[Action, ...]]:
    """answered and retry requeue a parked ticket; retry model reloads the model."""
    if event.kind == "retry" and event.key == "model":
        state = replace(_drop_needs(state, "model"), load_tries=0)
        return state, (Action("load_model", model=PHASE_MODEL.get(state.phase)),)
    found = _locate(state, event.key, "needs_you") or _locate(state, event.key)
    if found:
        i, ticket = found
        reopened = replace(
            ticket, verify_fails=0,
            status="changes" if ticket.findings else "pending")
        state = _place(state, i, reopened)
    return _dispatch(_drop_needs(state, event.key))


def _skip(state: State, event: Event) -> tuple[State, tuple[Action, ...]]:
    """Mark a parked ticket skipped, drop its entries, dispatch what is left."""
    found = _locate(state, event.key)
    if found:
        i, ticket = found
        state = _place(state, i, replace(ticket, status="skipped"))
    return _dispatch(_drop_needs(state, event.key))


def _block_check(
    state: State,
) -> tuple[State, tuple[Action, ...]]:
    """Park every pending ticket whose dependency is parked or skipped.

    Parked first, so a dependency parked here blocks its own dependents in the
    same pass. The dependency key goes into the needs_you detail, so `retry`
    names the dependency the human has to answer.
    """
    actions: list[Action] = []
    for i, _ in enumerate(state.lanes):
        for ticket in state.lanes[i].tickets:
            if ticket.status != "pending":
                continue
            dep = next(
                (d for d in ticket.depends_on
                 if status(state, d) in ("needs_you", "skipped")),
                None,
            )
            if dep is None:
                continue
            state = _place(state, i, replace(ticket, status="needs_you"))
            state = replace(state, needs_you=state.needs_you + (
                NeedsYou(ticket.key, "dependency_blocked", dep),))
            actions.append(
                Action("notify", key=ticket.key, detail=f"dependency_blocked: {ticket.key}"))
    return state, tuple(actions)


def _dispatch(state: State) -> tuple[State, tuple[Action, ...]]:
    """Release blocked tickets, give one ticket to every idle lane, then end the phase."""
    state, block_actions = _block_check(state)
    if state.phase == "pr":
        return _dispatch_pr(state, block_actions)
    if state.phase == "review":
        review_state, review_actions = _dispatch_review(state)
        return review_state, block_actions + review_actions
    if state.phase != "flash":
        return state, block_actions

    actions: list[Action] = list(block_actions)
    lanes: list[Lane] = []

    for lane in state.lanes:
        if lane.busy:
            lanes.append(lane)
            continue
        # A lane whose PR review objected spends this flash phase on the fix. The
        # objection text stays in pr_status, so no new state field carries it.
        if lane.pr_status.startswith(OBJECTION_PREFIX) and finished(lane):
            actions.append(
                Action(
                    "pr_fix",
                    key=lane.repo,
                    model=PHASE_MODEL["flash"],
                    detail=lane.pr_status[len(OBJECTION_PREFIX):],
                )
            )
            lanes.append(replace(lane, busy=True, pr_status="fixing"))
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
        # A lane that already spent its one PR retry goes back for a second review,
        # instead of a review phase over tickets that are all approved.
        if any(
            finished(lane) and lane.pr_status == "none" and lane.pr_tries == 1
            for lane in state.lanes
        ):
            actions.append(Action("load_model", model=PHASE_MODEL["pr"]))
            return replace(state, phase="pr", model=""), tuple(actions)
        review_model = PHASE_MODEL["review"]
        actions.append(Action("load_model", model=review_model))
        return replace(state, phase="review", model=""), tuple(actions)

    return state, tuple(actions)


def _dispatch_pr(
    state: State, actions: tuple[Action, ...]
) -> tuple[State, tuple[Action, ...]]:
    """Give one PR review to every idle, finished lane whose pr_status is still none."""
    lanes: list[Lane] = []
    pr_actions = list(actions)

    for lane in state.lanes:
        if lane.busy or lane.pr_status != "none" or not finished(lane):
            lanes.append(lane)
            continue
        pr_actions.append(Action("pr_review", key=lane.repo, model=PHASE_MODEL["pr"]))
        lanes.append(replace(lane, busy=True, pr_status="running"))

    state = replace(state, lanes=tuple(lanes))
    if len(pr_actions) > len(actions) or any(lane.busy for lane in state.lanes):
        return state, tuple(pr_actions)
    # Nothing to review: released tickets send the run back, else close the round.
    if _open_ticket_work(state):
        return _back_to_work(state, tuple(pr_actions))
    objected = any(lane.pr_status.startswith(OBJECTION_PREFIX) for lane in state.lanes)
    parked = any(t.status == "needs_you" for lane in state.lanes for t in lane.tickets)
    if objected or not parked:
        return _pr_phase_end(state, tuple(pr_actions))
    return state, tuple(pr_actions)  # only parked work left: wait for the user


def _open_ticket_work(state: State) -> bool:
    """Work the run can do now: ready pending tickets, or changes/implemented/fixed ones."""
    return any(
        ready_tickets(state, lane)
        or any(t.status in ("changes", "implemented", "fixed") for t in lane.tickets)
        for lane in state.lanes)


def _back_to_work(state: State, actions: tuple[Action, ...]) -> tuple[State, tuple[Action, ...]]:
    """A ticket released in the pr phase goes back through review or flash."""
    if any(t.status in ("implemented", "fixed") for lane in state.lanes for t in lane.tickets):
        return replace(state, phase="review", model=""), actions + (
            Action("load_model", model=PHASE_MODEL["review"]),)
    return replace(state, phase="flash", model=""), actions + (
        Action("load_model", model=PHASE_MODEL["flash"]),)


def _pr_phase_end(
    state: State, actions: tuple[Action, ...]
) -> tuple[State, tuple[Action, ...]]:
    """Close the pr round once no lane is busy: objections go to flash, else done."""
    if state.phase != "pr" or any(lane.busy for lane in state.lanes):
        return state, actions
    if any(finished(lane) and lane.pr_status == "none" for lane in state.lanes):
        return state, actions
    if any(lane.pr_status.startswith(OBJECTION_PREFIX) for lane in state.lanes):
        return replace(state, phase="flash", model=""), actions + (
            Action("load_model", model=PHASE_MODEL["flash"]),
        )
    return replace(state, phase="done"), actions + (Action("write_summary"),)


def _pr_reviewed(
    state: State, event: Event
) -> tuple[State, tuple[Action, ...]]:
    """Record a PR verdict: open the PR, spend the one retry, or park the repo."""
    found = _lane_by_repo(state, event.key)
    if found is None or found[1].pr_status != "running":
        return state, ()
    i, lane = found
    lane = replace(lane, busy=False)

    if event.ok:
        state = _set_lane(state, i, replace(lane, pr_status="approved"))
        actions: tuple[Action, ...] = (Action("open_pr", key=lane.repo),)
    elif lane.pr_tries == 0:
        # The first objection keeps the lane free and emits nothing: the flash
        # phase end is what routes this repo to pr_fix.
        state = _set_lane(state, i, replace(
            lane, pr_tries=1, pr_status=OBJECTION_PREFIX + event.detail))
        actions = ()
    else:
        state = _parked_repo(state, i, lane, event.detail)
        actions = (_notify_repo(lane.repo, event.detail),)
    return _pr_phase_end(state, actions)


def _pr_fixed(state: State, event: Event) -> tuple[State, tuple[Action, ...]]:
    """Record a pr_fix result: clear the objection, or treat a failure as a second one."""
    found = _lane_by_repo(state, event.key)
    if found is None or found[1].pr_status != "fixing":
        return state, ()
    i, lane = found
    lane = replace(lane, busy=False)

    if not event.ok:
        state = _parked_repo(state, i, lane, event.detail)
        return state, (_notify_repo(lane.repo, event.detail),)
    return _dispatch(_set_lane(state, i, replace(lane, pr_status="none")))


def _parked_repo(state: State, i: int, lane: Lane, detail: str) -> State:
    """This lane goes to Needs you with reason `pr_objected_twice`."""
    state = _set_lane(state, i, replace(lane, pr_status="needs_you"))
    return replace(state, needs_you=state.needs_you + (
        NeedsYou(lane.repo, "pr_objected_twice", detail),))


def _notify_repo(repo: str, detail: str) -> Action:
    """Tell the human this repo got its second PR objection."""
    return Action("notify", key=repo, detail=f"pr_objected_twice: {repo}")


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
    ready_now = any(ready_tickets(state, lane) for lane in state.lanes)
    if not changes and not next_batch_pending and not ready_now:
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
