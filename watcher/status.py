"""Status view: one JSON document for every UI, plus a human text render (ticket 18)."""

from __future__ import annotations

from typing import Any

from .types import Lane, State, TICKET_STATUSES

SCHEMA_VERSION = 1
_DETAIL_CHARS = 60
_REPO_COL = 20


def _counts(lane: Lane) -> dict[str, int]:
    """Count this lane's tickets by status; every status appears, zero when none."""
    counts = {status: 0 for status in TICKET_STATUSES}
    for ticket in lane.tickets:
        if ticket.status in counts:
            counts[ticket.status] += 1
    return counts


def _running(lane: Lane) -> str | None:
    """Return the key of the lane's `running` ticket, or None when no ticket runs."""
    for ticket in lane.tickets:
        if ticket.status == "running":
            return ticket.key
    return None


def _pr_status(value: str) -> str:
    """Normalise a lane PR status; any `objected:...` detail becomes `objected`."""
    return "objected" if value.startswith("objected") else value


def _lane_doc(lane: Lane) -> dict[str, Any]:
    """Build one lane's entry in the status document."""
    return {"repo": lane.repo, "busy": lane.busy, "pr_status": _pr_status(lane.pr_status),
            "counts": _counts(lane), "running": _running(lane),
            "tickets": [{"key": t.key, "title": t.title, "status": t.status, "sha": t.sha,
                         "depends_on": list(t.depends_on), "verify_fails": t.verify_fails,
                         "fix_rounds": t.fix_rounds} for t in lane.tickets]}


def status_doc(state: State) -> dict:
    """Build the versioned status document that every UI reads."""
    return {
        "schema": SCHEMA_VERSION,
        "prd": state.prd,
        "phase": state.phase,
        "batch": state.batch,
        "model": state.model,
        "needs_you": [{"key": n.key, "reason": n.reason, "detail": n.detail}
                      for n in state.needs_you],
        "lanes": [_lane_doc(lane) for lane in state.lanes],
    }


def render_text(doc: dict) -> str:
    """Render a status document as lines for a terminal."""
    needs_you = doc["needs_you"]
    lines = [f"{doc['prd']}  phase={doc['phase']}  batch={doc['batch']}"
             f"  model={doc['model'] or '-'}",
             f"NEEDS YOU ({len(needs_you)})"]
    lines += [f"  {n['key']}  {n['reason']}  {n['detail'][:_DETAIL_CHARS]}" for n in needs_you]
    for lane in doc["lanes"]:
        counts = lane["counts"]
        lines.append(f"  {lane['repo']:<{_REPO_COL}} {counts['approved']}/{sum(counts.values())}"
                     f" approved  running={lane['running'] or '-'}  pr={lane['pr_status']}")
    return "\n".join(lines)
