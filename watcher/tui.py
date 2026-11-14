"""Terminal UI screen: draw the status document and run watcher commands from key presses (ticket 25).

The screen never writes state. Every key runs a `watcher` command through the given `run`.
"""

from __future__ import annotations

import curses
import json
import subprocess

from .tui_model import Row, build_rows, command_for

_ALERT_PAIR, _BUSY_PAIR = 1, 2
_DOWN, _UP = ("j", "KEY_DOWN"), ("k", "KEY_UP")
_ANSWER_KEY = "a"
# Fields watcher.tui_model reads on every lane; a partial status document still draws with them.
_LANE_DEFAULTS = {"busy": False, "pr_status": "", "running": None, "counts": {"approved": 0}}


def fetch_doc(prd: str, run=subprocess.run) -> dict:
    """Return the status document that `watcher status --json` prints for this prd."""
    result = run(["watcher", "status", "--json", "--prd", prd],
                 capture_output=True, text=True, check=True)
    return json.loads(result.stdout)


def _attr(style: str) -> int:
    """Return the screen attribute for one view-model style name."""
    if style == "header":
        return curses.A_BOLD
    pair = {"alert": _ALERT_PAIR, "busy": _BUSY_PAIR}.get(style)
    return curses.color_pair(pair) if pair is not None else 0


def _lane(lane: dict) -> dict:
    """Return this lane with the fields the view-model reads filled in when absent."""
    return {**_LANE_DEFAULTS, **lane}


def _text(value) -> str:
    """Return a line read from the screen as text."""
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _first_line(result) -> str:
    """Return the first line of a command's output, or empty text when it printed nothing."""
    lines = (getattr(result, "stdout", "") or "").splitlines()
    return lines[0] if lines else ""


def _clamp(index: int, count: int) -> int:
    """Return index moved inside 0..count-1, or 0 when there is no row to select."""
    return 0 if count == 0 else max(0, min(index, count - 1))


def loop(stdscr, prd: str, refresh: float = 2.0, run=subprocess.run) -> None:
    """Draw the status every `refresh` seconds; `j`/`k` select, `q` exits, other keys run watcher."""
    stdscr.timeout(max(int(refresh * 1000), 100))  # never 0: no busy loop
    selected, rows, note, error = 0, [], "", ""
    while True:
        total, cols = stdscr.getmaxyx()  # read each redraw so a resize cannot overflow
        try:
            doc = fetch_doc(prd, run=run)
            rows = build_rows({**doc, "lanes": [_lane(lane) for lane in doc["lanes"]]},
                              cols - 1, selected)
            error = ""
        except Exception as exc:
            rows, error = [], f"status unavailable: {exc}"
        for index, row in enumerate(rows[:max(total - 1, 0)]):  # keep the last line free
            stdscr.addstr(index, 0, row.text[:cols - 1], _attr(row.style))
        stdscr.addstr(total - 1, 0, (error or note)[:cols - 1])
        try:
            key = stdscr.getkey()
        except curses.error:  # no key before the refresh timeout: redraw
            continue
        if key == "q":
            return
        if key in _DOWN:
            selected = _clamp(selected + 1, len(rows))
        elif key in _UP:
            selected = _clamp(selected - 1, len(rows))
        elif rows:
            output = _command(key, rows[selected], stdscr, total, cols, run)
            if output is not None:
                note = output


def _command(key: str, row: Row, stdscr, total: int, cols: int, run) -> str | None:
    """Run the watcher command this key binds on that row and return its first output line."""
    cmd = command_for(key, row)
    if cmd is None:
        return None
    if key == _ANSWER_KEY:
        stdscr.echo()
        cmd = cmd + [_text(stdscr.getstr(total - 1, 0, cols - 1))]
        stdscr.noecho()
    return _first_line(run(cmd, capture_output=True, text=True, check=False))


def main(prd: str) -> int:
    """Run the screen through curses and return the exit code."""
    curses.wrapper(loop, prd)
    return 0
