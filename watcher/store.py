"""Atomic state file and JSONL event log.

State saves through a temp file and one os.replace, so a crash leaves the
previous state.json whole. Every event appends as one JSON line.
"""

from __future__ import annotations

import json
import os

from watcher.types import Event, State, event_from_json, state_from_json, to_json

STATE_FILE = "state.json"
EVENTS_FILE = "events.jsonl"


def _default_root() -> str:
    """Return the state root: $XDG_STATE_HOME, else ~/.local/state."""
    return os.environ.get("XDG_STATE_HOME") or os.path.expanduser("~/.local/state")


def state_dir(prd: str, root: str | None = None) -> str:
    """Return the directory that holds one PRD's state file and event log."""
    return os.path.join(root if root is not None else _default_root(), "watcher", prd)


def list_prds(root: str | None = None) -> list[str]:
    """Return the sorted names of the folders under the state root that hold a state.json."""
    parent = os.path.dirname(state_dir("", root))
    if not os.path.isdir(parent):
        return []
    return sorted(
        name
        for name in os.listdir(parent)
        if os.path.isfile(os.path.join(state_dir(name, root), STATE_FILE))
    )


def _fsync_dir(path: str) -> None:
    """Fsync a directory so the rename inside it survives a crash."""
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def save(state: State, root: str | None = None) -> None:
    """Write state.json atomically: temp file, fsync, replace, fsync directory."""
    directory = state_dir(state.prd, root)
    os.makedirs(directory, exist_ok=True)
    tmp = os.path.join(directory, STATE_FILE + ".tmp")
    final = os.path.join(directory, STATE_FILE)
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(to_json(state), f, indent=2, sort_keys=True)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, final)
    _fsync_dir(directory)


def load(prd: str, root: str | None = None) -> State | None:
    """Return the saved State for a prd, or None when no state file exists."""
    final = os.path.join(state_dir(prd, root), STATE_FILE)
    if not os.path.exists(final):
        return None
    with open(final, encoding="utf-8") as f:
        return state_from_json(json.load(f))


def append_event(prd: str, event: Event, root: str | None = None) -> None:
    """Append one event as a JSON line and fsync the log."""
    directory = state_dir(prd, root)
    os.makedirs(directory, exist_ok=True)
    with open(os.path.join(directory, EVENTS_FILE), "a", encoding="utf-8") as f:
        f.write(json.dumps(to_json(event)) + "\n")
        f.flush()
        os.fsync(f.fileno())


def read_events(prd: str, root: str | None = None) -> list[Event]:
    """Return the logged events in append order, skipping a torn final line."""
    path = os.path.join(state_dir(prd, root), EVENTS_FILE)
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as f:
        lines = f.read().splitlines()
    events: list[Event] = []
    for index, line in enumerate(lines):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            if index == len(lines) - 1:
                break
            raise
        events.append(event_from_json(data))
    return events
