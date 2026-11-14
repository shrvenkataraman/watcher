"""Terminal UI view-model rows and key bindings (watcher ticket 24)."""
import copy

import pytest

from watcher.tui_model import Row, build_rows, command_for

REVIEW = "qwen3.8-27b-w8a8"

DOC = {
    "schema": 1,
    "prd": "demo",
    "phase": "review",
    "batch": 1,
    "model": REVIEW,
    "needs_you": [{"key": "quark-kit/07", "reason": "question", "detail": "Which base?"}],
    "lanes": [
        {"repo": "quark-kit", "busy": True, "pr_status": "none",
         "running": "quark-kit/02",
         "counts": {"pending": 2, "running": 1, "implemented": 0, "fixed": 0,
                    "changes": 0, "approved": 3, "needs_you": 1, "skipped": 0}},
        {"repo": "qresearch", "busy": False, "pr_status": "objected: keep it small",
         "running": None,
         "counts": {"pending": 0, "running": 0, "implemented": 0, "fixed": 0,
                    "changes": 0, "approved": 1, "needs_you": 0, "skipped": 0}},
    ],
}


def _pad(s: str, width: int) -> str:
    """Independent expected-value builder: pad, or truncate with one final ellipsis."""
    if len(s) <= width:
        return s + " " * (width - len(s))
    return s[:width - 1] + "…"


def test_row_fields_exist():
    r = Row("x", "plain", None)
    assert (r.text, r.style, r.key) == ("x", "plain", None)


def test_AC1_fixture_rows_at_width_80():
    rows = build_rows(copy.deepcopy(DOC), 80, selected=0)
    assert [r.style for r in rows] == ["header", "header", "alert", "plain",
                                       "header", "busy", "lane"]
    body0 = _pad(f"watcher demo  phase review  batch 1  model {REVIEW}", 80)
    assert rows[0].text[2:] == body0[2:] and rows[0].text.startswith("> ")
    assert rows[1].text == _pad("NEEDS YOU (1)", 80)
    assert rows[2].text == _pad("! quark-kit/07  question  Which base?", 80)
    assert rows[2].key == "quark-kit/07"
    assert rows[3].text == " " * 80
    assert rows[4].text == _pad("LANES", 80)
    assert rows[5].text == _pad("  quark-kit           ####...... 3/7  quark-kit/02  "
                                "pr:none", 80)
    assert rows[5].key == "quark-kit"
    assert rows[6].text == _pad("  qresearch           ########## 1/1  idle  "
                                "pr:objected", 80)


@pytest.mark.parametrize("width", [20, 40, 80, 200])
def test_AC2_every_row_is_exactly_width(width):
    for row in build_rows(copy.deepcopy(DOC), width):
        assert len(row.text) == width


def test_truncation_uses_final_ellipsis():
    row = build_rows(copy.deepcopy(DOC), 20)[5]
    assert row.text[-1] == "…"


def test_selection_marker_moves():
    rows = build_rows(copy.deepcopy(DOC), 80, selected=2)
    assert rows[2].text.startswith("> ")
    assert not rows[0].text.startswith("> ")


def test_AC3_command_for_key_map():
    alert = build_rows(copy.deepcopy(DOC), 80)[2]
    assert command_for("r", alert) == ["watcher", "retry", "quark-kit/07"]
    assert command_for("s", alert) == ["watcher", "skip", "quark-kit/07"]
    assert command_for("a", alert) == ["watcher", "answer", "quark-kit/07"]
    assert command_for("A", alert) == ["watcher", "abort"]
    blank = build_rows(copy.deepcopy(DOC), 80)[3]
    assert command_for("r", blank) is None
    assert command_for("s", blank) is None
    assert command_for("a", blank) is None
    assert command_for("A", blank) == ["watcher", "abort"]


def test_AC4_schema_two_raises():
    bad = copy.deepcopy(DOC)
    bad["schema"] = 2
    with pytest.raises(ValueError, match="status schema"):
        build_rows(bad, 80)


def test_alert_row_count_matches_needs_you():
    empty = copy.deepcopy(DOC)
    empty["needs_you"] = []
    rows = build_rows(empty, 80)
    assert [r for r in rows if r.style == "alert"] == []
    assert any(r.text.strip() == "NEEDS YOU (0)" for r in rows)
