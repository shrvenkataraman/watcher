"""watcher board --all (multi-project ticket 07)."""
import pytest

from watcher import cli


@pytest.fixture
def execs(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "BOARD_BIN", "fake-board", raising=False)
    monkeypatch.setattr(cli.shutil, "which", lambda b: "/bin/" + b)
    monkeypatch.setattr(cli.os, "execvp", lambda f, a: calls.append((f, a)))
    return calls


def test_AC1_all_execs_board_all(execs):
    cli.main(["board", "--all"])
    assert execs == [("fake-board", ["fake-board", "--all"])]


def test_AC2_all_forwards_state_root(execs):
    cli.main(["board", "--all", "--state-root", "R"])
    assert execs[0][1] == ["fake-board", "--all", "--state-root", "R"]


def test_AC3_all_with_prd_is_refused(execs, capsys):
    assert cli.main(["board", "--all", "--prd", "p"]) == 2
    assert "not both" in capsys.readouterr().err and execs == []


def test_AC4_prd_still_works(execs):
    cli.main(["board", "--prd", "p"])
    assert execs[0][1] == ["fake-board", "--prd", "p"]


def test_AC5_all_without_binary_gives_hint(monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _b: None)
    assert cli.main(["board", "--all"]) == 2
    assert "cargo install --path kanban" in capsys.readouterr().err


@pytest.mark.parametrize("argv", [["board", "--all"], ["board", "--prd", "p"]])
def test_AC1_property_exactly_one_selector(execs, argv):
    cli.main(argv)
    selectors = [a for a in execs[0][1] if a in ("--all", "--prd")]
    assert len(selectors) == 1
