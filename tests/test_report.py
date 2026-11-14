"""Morning summary file and desktop alerts (watcher ticket 20)."""
import os

import pytest

from watcher.report import notify, write_summary
from watcher.types import Event, Lane, NeedsYou, State, TicketState

GLM = "glm-5.3-flash-maya"


def _fixture_state() -> State:
    return State(
        prd="demo", phase="pr", batch=2, model=GLM,
        lanes=(
            Lane("quark-kit", (
                TicketState("quark-kit/01", 0, status="approved"),
                TicketState("quark-kit/07", 0, status="needs_you", findings="Which base?"),
                TicketState("quark-kit/09", 0, status="skipped"),
            ), pr_status="objected: add tests"),
            Lane("qresearch", (TicketState("qresearch/01", 0, status="approved"),),
                 pr_status="approved"),
        ),
        needs_you=(
            NeedsYou("quark-kit/07", "question", "Which base?\nsecond line ignored"),
            NeedsYou("qresearch", "pr_objected_twice", "keep it small"),
        ),
        load_tries=0,
    )


EXPECTED = """# watcher: demo — 2026-11-14T09:00:00
Phase: pr, batch 2
## Needs you (2)
- quark-kit/07: question — Which base?
- qresearch: pr_objected_twice — keep it small
## Lanes
| repo | approved | needs you | skipped | PR |
| quark-kit | 1 | 1 | 1 | objected |
| qresearch | 1 | 0 | 0 | approved |
## Events
- implemented: 2
- reviewed: 1
"""


def _events():
    return [
        Event("implemented", key="quark-kit/01"),
        Event("implemented", key="quark-kit/02"),
        Event("reviewed", key="quark-kit/01", ok=False),
    ]


def test_AC1_summary_matches_golden(tmp_path):
    path = str(tmp_path / "summary.md")
    write_summary(_fixture_state(), _events(), path, now="2026-11-14T09:00:00")
    with open(path) as fh:
        assert fh.read() == EXPECTED


def test_summary_written_atomically_no_tmp_left(tmp_path):
    path = str(tmp_path / "summary.md")
    write_summary(_fixture_state(), _events(), path, now="2026-11-14T09:00:00")
    assert sorted(os.listdir(tmp_path)) == ["summary.md"]


@pytest.mark.parametrize("n", [0, 1, 3])
def test_needs_you_heading_count_matches_state(n):
    needs = tuple(NeedsYou(f"quark-kit/{i:02d}", "question", "why") for i in range(n))
    state = State(prd="demo", phase="flash", batch=0, model="",
                  lanes=(Lane("quark-kit", (TicketState("quark-kit/01", 0),),),),
                  needs_you=needs, load_tries=0)
    path = "/tmp/watcher-t20-count.md"
    write_summary(state, [], path, now="2026-11-14T09:00:00")
    with open(path) as fh:
        assert f"## Needs you ({n})" in fh.read()
    os.remove(path)


def test_AC2_notify_calls_notify_send_critical():
    calls = []

    def spy_run(argv, check=True):
        calls.append((argv, check))

    notify("watcher needs you", "quark-kit/07: question", run=spy_run)
    assert calls == [(["notify-send", "-a", "watcher", "-u", "critical",
                       "watcher needs you", "quark-kit/07: question"], False)]


def test_AC3_missing_notify_send_raises_nothing():
    def boom(argv, check=True):
        raise FileNotFoundError("notify-send")

    notify("t", "b", run=boom)  # must not raise
