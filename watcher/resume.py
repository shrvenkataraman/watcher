"""Reconcile persisted state with git history after a crash (watcher ticket 14).

`reconcile(state, committed)` takes the commit map from git (`repo -> {key: sha}`)
and returns a state where no committed ticket reruns and no ticket stays `running`.
Pure function: it reads no files and writes no state.
"""

from __future__ import annotations

from dataclasses import replace

from .types import Lane, State, TicketState

PR_STATUS_AFTER_RESET = {"running": "none", "fixing": "objected:"}


def _reconcile_ticket(ticket: TicketState, committed: dict[str, str]) -> TicketState:
    """Apply the ticket rules; the commit map wins over an in-flight status."""
    if ticket.status == "running":
        if ticket.key in committed:
            return replace(ticket, status="implemented", sha=committed[ticket.key])
        if ticket.findings and ticket.fix_rounds == 0:
            return replace(ticket, status="changes")
        return replace(ticket, status="pending")
    if ticket.status == "pending" and ticket.key in committed:
        return replace(ticket, status="implemented", sha=committed[ticket.key])
    return ticket


def _reconcile_lane(lane: Lane, committed: dict[str, str]) -> Lane:
    """Free the lane, reset its PR status and reconcile every ticket in it."""
    tickets = tuple(_reconcile_ticket(t, committed) for t in lane.tickets)
    pr_status = PR_STATUS_AFTER_RESET.get(lane.pr_status, lane.pr_status)
    return replace(lane, tickets=tickets, pr_status=pr_status, busy=False)


def reconcile(state: State, committed: dict[str, dict[str, str]]) -> State:
    """Return a state whose ticket statuses match git, with every lane free."""
    lanes = tuple(
        _reconcile_lane(lane, committed.get(lane.repo, {})) for lane in state.lanes
    )
    return replace(state, lanes=lanes, model="")
