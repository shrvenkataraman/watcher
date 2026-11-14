"""hk adapter: lane creation and receipt reading (watcher ticket 16)."""
import json
import os
import stat

import pytest

from watcher import hk as hkmod

FAKE = os.path.join(os.path.dirname(__file__), "fakes", "bin", "hk")


@pytest.fixture
def fake_hk(tmp_path, monkeypatch):
    os.chmod(FAKE, os.stat(FAKE).st_mode | stat.S_IEXEC)
    monkeypatch.setattr(hkmod, "HK", FAKE)
    log = tmp_path / "calls.log"
    monkeypatch.setenv("HK_LOG", str(log))
    root = tmp_path / "workroot"
    root.mkdir()
    return str(root), log


def _receipt(tmp_path, name, payload):
    p = tmp_path / name
    p.write_text(json.dumps(payload))
    return str(p)


def test_AC1_ensure_lane_calls_hk_once_with_base_and_check(fake_hk, tmp_path, monkeypatch):
    root, log = fake_hk
    wt = hkmod.ensure_lane("earnings-q4", "quark-kit", "develop", "uv run pytest -q", root)
    assert wt == hkmod.lane_worktree(root, "earnings-q4", "quark-kit")
    calls = log.read_text().splitlines()
    assert calls == [f"{root} new --task earnings-q4 --repo quark-kit --base develop --check uv run pytest -q"]
    again = hkmod.ensure_lane("earnings-q4", "quark-kit", "develop", "uv run pytest -q", root)
    assert again == wt
    assert len(log.read_text().splitlines()) == 1  # contract exists: hk is not called again


def test_AC1_hk_failure_raises_runtime_error(fake_hk, monkeypatch):
    root, _ = fake_hk
    monkeypatch.setenv("NEW_FAIL", "1")
    with pytest.raises(RuntimeError, match="repo not registered"):
        hkmod.ensure_lane("earnings-q4", "ghost-repo", "develop", "uv run pytest -q", root)


def _verify_with(tmp_path, monkeypatch, fake_hk, receipt=None, stderr=None):
    root, _ = fake_hk
    wt = os.path.join(root, "features", "p", "r")
    os.makedirs(wt, exist_ok=True)
    if receipt:
        monkeypatch.setenv("FAKE_RECEIPT", receipt)
    if stderr:
        monkeypatch.setenv("FAKE_STDERR", stderr)
    return hkmod.verify(wt)


def test_AC2_green_receipt(fake_hk, tmp_path, monkeypatch):
    rec = _receipt(tmp_path, "g.json", {
        "verdict": "green",
        "checks": [{"exec": "uv run pytest -q", "exit_code": 0, "output_tail": "53 passed"}],
        "checks_passed": 1, "checks_failed": 0,
        "files_changed": 2, "lines_changed": 41, "scope_ok": True,
    })
    res = _verify_with(tmp_path, monkeypatch, fake_hk, receipt=rec)
    assert res.green is True


def test_AC3_red_receipt_gives_failed_output_tail(fake_hk, tmp_path, monkeypatch):
    rec = _receipt(tmp_path, "r.json", {
        "verdict": "red",
        "checks": [
            {"exec": "lint", "exit_code": 0, "output_tail": "all good"},
            {"exec": "tests", "exit_code": 1, "output_tail": "FAILED test_x\n1 failed"},
        ],
        "checks_passed": 1, "checks_failed": 1,
        "files_changed": 2, "lines_changed": 41, "scope_ok": True,
    })
    res = _verify_with(tmp_path, monkeypatch, fake_hk, receipt=rec, stderr="receipt red")
    assert res.green is False
    assert "FAILED test_x" in res.tail
    assert "all good" not in res.tail


def test_AC4_scope_ok_false_gives_scope_tail(fake_hk, tmp_path, monkeypatch):
    rec = _receipt(tmp_path, "s.json", {
        "verdict": "red",
        "checks": [{"exec": "tests", "exit_code": 0, "output_tail": "ok"}],
        "checks_passed": 1, "checks_failed": 0,
        "files_changed": 4, "lines_changed": 300, "scope_ok": False,
    })
    res = _verify_with(tmp_path, monkeypatch, fake_hk, receipt=rec)
    assert res.green is False
    assert res.tail == "scope: 4 files, 300 lines"


def test_missing_receipt_gives_stderr_tail(fake_hk, tmp_path, monkeypatch):
    res = _verify_with(tmp_path, monkeypatch, fake_hk, stderr="hk: no contract here")
    assert res.green is False
    assert "no contract" in res.tail


@pytest.mark.parametrize("verdict,expect_green", [("green", True), ("red", False)])
def test_AC2_result_agrees_with_verdict(fake_hk, tmp_path, monkeypatch, verdict, expect_green):
    rec = _receipt(tmp_path, "v.json", {
        "verdict": verdict, "checks": [], "checks_passed": 0, "checks_failed": 0,
        "files_changed": 1, "lines_changed": 1, "scope_ok": True,
    })
    res = _verify_with(tmp_path, monkeypatch, fake_hk, receipt=rec)
    assert res.green is expect_green
