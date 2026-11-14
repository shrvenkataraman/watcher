"""Core value types for the watcher orchestrator.

Frozen dataclasses for state, events and actions, plus JSON round-trip helpers.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, fields
from typing import Any

PHASE_MODEL = {
    "flash": "qwen3.8-flash-next",
    "review": "qwen3.8-27b-w8a8",
    "pr": "glm-5.3-flash-maya",
    "done": None,
}

TICKET_STATUSES = (
    "pending",
    "running",
    "implemented",
    "approved",
    "changes",
    "fixed",
    "needs_you",
    "skipped",
)


@dataclass(frozen=True)
class TicketState:
    key: str
    batch: int
    depends_on: tuple[str, ...] = ()
    status: str = "pending"
    sha: str = ""
    verify_fails: int = 0
    fix_rounds: int = 0
    findings: str = ""


@dataclass(frozen=True)
class Lane:
    repo: str
    tickets: tuple[TicketState, ...]
    pr_status: str = "none"
    pr_tries: int = 0
    busy: bool = False


@dataclass(frozen=True)
class NeedsYou:
    key: str
    reason: str
    detail: str = ""


@dataclass(frozen=True)
class State:
    prd: str
    phase: str = "flash"
    batch: int = 0
    model: str = ""
    lanes: tuple[Lane, ...] = ()
    needs_you: tuple[NeedsYou, ...] = ()
    load_tries: int = 0
    models: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class Event:
    kind: str
    key: str = ""
    ok: bool = True
    sha: str = ""
    detail: str = ""


@dataclass(frozen=True)
class Action:
    kind: str
    key: str = ""
    model: str = ""
    detail: str = ""


def _lists(value: Any) -> Any:
    """Replace tuples with lists so the result round-trips through json."""
    if isinstance(value, dict):
        return {k: _lists(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_lists(v) for v in value]
    return value


def to_json(obj: Any) -> dict:
    """Convert a dataclass into JSON-friendly plain data."""
    return _lists(asdict(obj))


def _build(cls: type, d: dict) -> Any:
    """Build one dataclass from a dict, ignoring unknown keys, lists -> tuples."""
    kwargs: dict[str, Any] = {}
    for f in fields(cls):
        if f.name not in d:
            continue
        value = d[f.name]
        if isinstance(value, list):
            value = tuple(value)
        kwargs[f.name] = value
    return cls(**kwargs)


def state_from_json(d: dict) -> State:
    """Rebuild a State, including nested lanes, tickets and needs_you."""
    lanes = []
    for lane in d.get("lanes", ()):
        tickets = [_build(TicketState, ticket) for ticket in lane.get("tickets", ())]
        lanes.append(_build(Lane, {**lane, "tickets": tickets}))
    needs_you = [_build(NeedsYou, item) for item in d.get("needs_you", ())]
    models = [tuple(m) for m in d.get("models", ())]
    return _build(State, {**d, "lanes": lanes, "needs_you": needs_you, "models": models})


def event_from_json(d: dict) -> Event:
    """Rebuild an Event from plain data."""
    return _build(Event, d)
