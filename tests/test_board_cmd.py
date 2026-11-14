from __future__ import annotations

import pytest

from watcher import cli


def test_AC1_missing_binary_exits_2_with_install_hint(monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _b: None)
    assert cli.main(["board", "--prd", "p"]) == 2
    assert "cargo install --path kanban" in capsys.readouterr().err


def test_AC2_execs_board_with_prd(monkeypatch):
    calls = []
    monkeypatch.setattr(cli, "BOARD_BIN", "fake-board", raising=False)
    monkeypatch.setattr(cli.shutil, "which", lambda b: "/bin/" + b)
    monkeypatch.setattr(cli.os, "execvp", lambda f, a: calls.append((f, a)))
    cli.main(["board", "--prd", "p"])
    assert calls == [("fake-board", ["fake-board", "--prd", "p"])]


def test_AC3_forwards_state_root(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(cli, "BOARD_BIN", "fake-board", raising=False)
    monkeypatch.setattr(cli.shutil, "which", lambda b: "/bin/" + b)
    monkeypatch.setattr(cli.os, "execvp", lambda f, a: calls.append((f, a)))
    cli.main(["board", "--prd", "p", "--state-root", str(tmp_path)])
    assert calls[0][1] == ["fake-board", "--prd", "p", "--state-root", str(tmp_path)]


def test_unresolved_prd_exits_2(tmp_path, capsys):
    assert cli.main(["board", "--state-root", str(tmp_path)]) == 2
    assert "no state for prd" in capsys.readouterr().err
