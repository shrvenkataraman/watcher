"""Morning summary file and desktop alerts (watcher ticket 20)."""

from __future__ import annotations

import os
import subprocess
from collections import Counter

from .status import status_doc
from .types import Event, State

_TMP_SUFFIX = ".tmp"


def _first_line(detail: str) -> str:
    """Return the first line of a detail; an empty detail gives an empty string."""
    return detail.splitlines()[0] if detail else ""


def _lines(state: State, events: list[Event], now: str) -> list[str]:
    """Build the summary's lines: heading, Needs you, Lanes table, Events counts."""
    lanes = status_doc(state)["lanes"]
    lines = [f"# watcher: {state.prd} — {now}",
             f"Phase: {state.phase}, batch {state.batch}",
             f"## Needs you ({len(state.needs_you)})"]
    lines += [f"- {item.key}: {item.reason} — {_first_line(item.detail)}"
              for item in state.needs_you]
    lines.append("## Lanes")
    lines.append("| repo | approved | needs you | skipped | PR |")
    lines += [f"| {lane['repo']} | {lane['counts']['approved']}"
              f" | {lane['counts']['needs_you']} | {lane['counts']['skipped']}"
              f" | {lane['pr_status']} |" for lane in lanes]
    lines.append("## Events")
    counts = Counter(event.kind for event in events)
    lines += [f"- {kind}: {counts[kind]}" for kind in sorted(counts)]
    return lines


def write_summary(state: State, events: list[Event], path: str, now: str) -> None:
    """Write the morning summary to `path` atomically: a tmp file, then os.replace."""
    tmp = f"{path}{_TMP_SUFFIX}"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write("\n".join(_lines(state, events, now)) + "\n")
    os.replace(tmp, path)


def notify(title: str, body: str, run=subprocess.run) -> None:
    """Send one desktop alert with notify-send; a missing binary raises nothing."""
    try:
        run(["notify-send", "-a", "watcher", "-u", "critical", title, body], check=False)
    except FileNotFoundError:
        pass
