"""Terminal UI view-model: status document to screen rows and key bindings (ticket 24)."""

from __future__ import annotations

from dataclasses import dataclass

from .status import _pr_status

_INDENT = "  "
_REPO_COL = 20
_BAR = 10
_ELLIPSIS = "…"
_MARKER = "> "


@dataclass(frozen=True)
class Row:
    """One screen line: text already sized to the width, its style, and its action key."""

    text: str
    style: str
    key: str | None = None


def _fit(text: str, width: int) -> str:
    """Return text padded with spaces, or truncated with a final ellipsis, to exactly width."""
    if len(text) <= width:
        return text + " " * (width - len(text))
    return text[:width - 1] + _ELLIPSIS


def _bar(approved: int, total: int) -> str:
    """Return the 10-char progress bar: filled by the approved share, dotted for the rest."""
    filled = round(_BAR * approved / total) if total else 0
    return "#" * filled + "." * (_BAR - filled)


def _lane_row(lane: dict) -> Row:
    """Build one lane's un-fitted row: repo column, bar, approved count, running key, PR status."""
    counts = lane["counts"]
    approved = counts["approved"]
    total = sum(counts.values())
    text = (f"{_INDENT}{lane['repo']:<{_REPO_COL}}{_bar(approved, total)}"
            f" {approved}/{total}  {lane['running'] or 'idle'}"
            f"  pr:{_pr_status(lane['pr_status'])}")
    return Row(text, "busy" if lane["busy"] else "lane", lane["repo"])


def build_rows(doc: dict, width: int, selected: int = 0) -> list[Row]:
    """Turn a status document into the exact rows the terminal UI draws."""
    if doc["schema"] != 1:
        raise ValueError("status schema")
    needs_you = doc["needs_you"]
    rows = [
        Row(f"watcher {doc['prd']}  phase {doc['phase']}  batch {doc['batch']}"
            f"  model {doc['model'] or '-'}", "header"),
        Row(f"NEEDS YOU ({len(needs_you)})", "header"),
    ]
    rows += [Row(f"! {n['key']}  {n['reason']}  {n['detail']}", "alert", n["key"])
             for n in needs_you]
    rows.append(Row("", "plain"))
    rows.append(Row("LANES", "header"))
    rows += [_lane_row(lane) for lane in doc["lanes"]]
    sized = [Row(_fit(row.text, width), row.style, row.key) for row in rows]
    if 0 <= selected < len(sized) and len(sized[selected].text) >= len(_MARKER):
        marked = _MARKER + sized[selected].text[len(_MARKER):]
        sized[selected] = Row(marked, sized[selected].style, sized[selected].key)
    return sized


def command_for(key_pressed: str, row: Row) -> list[str] | None:
    """Return the watcher command a key runs on this row, or None when the key binds nothing."""
    if key_pressed == "A":
        return ["watcher", "abort"]
    verbs = {"r": "retry", "s": "skip", "a": "answer"}
    verb = verbs.get(key_pressed)
    if verb is None or row.key is None:
        return None
    return ["watcher", verb, row.key]
