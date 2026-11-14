"""CLI commands status/inbox/show/answer/retry/skip/abort (watcher ticket 19)."""
import json
import os

import pytest

from watcher.cli import main
from watcher.status import render_text, status_doc
from watcher.store import save
from watcher.types import Lane, NeedsYou, State, TicketState

REVIEW = "qwen3.8-27b-w8a8"


def _fixture_state() -> State:
    return State(
        prd="demo", phase="review", batch=1, model=REVIEW,
        lanes=(
            Lane("quark-kit", (
                TicketState("quark-kit/01", 0, status="approved"),
                TicketState("quark-kit/02", 0, status="running"),
                TicketState("quark-kit/07", 0, status="needs_you", findings="Which base?"),
            ), pr_status="none", busy=True),
            Lane("qresearch", (TicketState("qresearch/01", 0, status="skipped"),),
                 pr_status="objected: add tests"),
        ),
        needs_you=(NeedsYou("quark-kit/07", "question", "Which base?"),),
        load_tries=0,
    )


@pytest.fixture
def root(tmp_path):
    save(_fixture_state(), root=str(tmp_path))
    return str(tmp_path)


def _args(root, *cmd):
    return [*cmd, "--prd", "demo", "--state-root", root]


def _queue(root):
    path = os.path.join(root, "watcher", "demo", "queue.jsonl")
    if not os.path.exists(path):
        return []
    with open(path) as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _state_bytes(root):
    with open(os.path.join(root, "watcher", "demo", "state.json"), "rb") as fh:
        return fh.read()


def test_AC1_status_text_matches_render(root, capsys):
    assert main(_args(root, "status")) == 0
    assert capsys.readouterr().out.strip() == render_text(status_doc(_fixture_state())).strip()


def test_AC1_status_json_matches_status_doc(root, capsys):
    assert main(_args(root, "status", "--json")) == 0
    assert json.loads(capsys.readouterr().out) == json.loads(
        json.dumps(status_doc(_fixture_state())))


def test_AC2_inbox_exit_codes(root, capsys):
    assert main(_args(root, "inbox")) == 3
    out = capsys.readouterr().out
    assert "NEEDS YOU (1)" in out and "quark-kit/07" in out
    save(State(prd="demo", phase="flash", batch=0, model="",
               lanes=(Lane("quark-kit", (TicketState("quark-kit/01", 0),),),),
               needs_you=(), load_tries=0), root=root)
    assert main(_args(root, "inbox")) == 0


def test_show_prints_ticket_and_needs_entries(root, capsys):
    assert main(_args(root, "show", "quark-kit/07")) == 0
    out = capsys.readouterr().out
    assert "needs_you" in out and "Which base?" in out


@pytest.mark.parametrize("cmd,key,want", [
    (["answer", "quark-kit/07", "Use develop"], "quark-kit/07", "answered"),
    (["retry", "quark-kit/07"], "quark-kit/07", "retry"),
    (["skip", "quark-kit/07"], "quark-kit/07", "skip"),
    (["abort"], "", "abort"),
])
def test_AC3_commands_append_one_queue_line(root, cmd, key, want):
    before = _state_bytes(root)
    assert main(_args(root, *cmd)) == 0
    lines = _queue(root)
    assert len(lines) == 1 and lines[0]["kind"] == want and lines[0]["key"] == key
    assert _state_bytes(root) == before  # AC4
    if want == "answered":
        with open(os.path.join(root, "watcher", "demo", "answers", "quark-kit_07.md")) as fh:
            text = fh.read()
        assert text.endswith("\n\n## Answer\nUse develop") or "## Answer\nUse develop" in text


def test_AC5_unknown_key_exits_2(root, capsys):
    assert main(_args(root, "retry", "zz/99")) == 2
    assert "unknown key: zz/99" in capsys.readouterr().err
    assert _queue(root) == []


def test_no_state_exits_2(tmp_path, capsys):
    assert main(_args(str(tmp_path), "status")) == 2
    assert "no state for prd" in capsys.readouterr().err


def test_default_prd_single_dir(root, capsys):
    assert main(["status", "--state-root", root]) == 0
    capsys.readouterr()


def test_ambiguous_prd_is_error(tmp_path):
    for prd in ("one", "two"):
        save(State(prd=prd, phase="flash", batch=0, model="",
                   lanes=(Lane("quark-kit", (TicketState("quark-kit/01", 0),),),),
                   needs_you=(), load_tries=0), root=str(tmp_path))
    # state root now holds two prd dirs under watcher/; default prd must be an error
    assert main(["status", "--state-root", str(tmp_path)]) == 2
