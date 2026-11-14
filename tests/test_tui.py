"""Frozen oracles for ticket 25: the curses tui screen (fetch, loop, keys, cli)."""
import json
import subprocess

from watcher import cli, tui, tui_model


def _doc():
    return {
        "schema": 1, "prd": "demo", "phase": "review", "batch": "qwen3-8b",
        "model": None, "lanes": [{"repo": "r1", "phase": "implement"}],
        "needs_you": [{"key": "demo/07", "reason": "strategy", "detail": "gate fail 3"}],
        "tickets": [],
    }


class FakeScreen:
    def __init__(self, keys, typed=()):
        self.keys = list(keys)
        self.typed = list(typed)
        self.drawn = []
        self.timeouts = []
        self.echoed = False

    def timeout(self, ms):
        self.timeouts.append(ms)

    def getmaxyx(self):
        return (24, 80)

    def getkey(self):
        return self.keys.pop(0) if self.keys else "q"

    def addstr(self, y, x, text, attr=0):
        self.drawn.append((y, str(text)))

    def echo(self):
        self.echoed = True

    def noecho(self):
        pass

    def getstr(self, *args):
        return self.typed.pop(0).encode() if self.typed else b""

    def clrtoeol(self):
        pass

    def refresh(self):
        pass


class FakeRun:
    def __init__(self, stdout="ok\nmore"):
        self.calls = []
        self.stdout = stdout

    def __call__(self, cmd, capture_output=False, text=False, check=True):
        self.calls.append((list(cmd), check))
        return subprocess.CompletedProcess(cmd, 0, stdout=self.stdout, stderr="")


def _prep(monkeypatch):
    monkeypatch.setattr(tui.curses, "color_pair", lambda n: n)


def test_fetch_doc_runs_status_json():
    run = FakeRun(stdout=json.dumps(_doc()))
    doc = tui.fetch_doc("demo", run=run)
    assert run.calls[0][0] == ["watcher", "status", "--json", "--prd", "demo"]
    assert doc["prd"] == "demo"


def test_AC4_q_returns_after_drawing_header_alert(monkeypatch):
    _prep(monkeypatch)
    run = FakeRun(stdout=json.dumps(_doc()))
    screen = FakeScreen(["q"])
    tui.loop(screen, "demo", refresh=2.0, run=run)
    assert screen.timeouts[0] == 2000
    texts = [t for _, t in screen.drawn]
    assert any("NEEDS YOU (1)" in t for t in texts)
    assert any(t.startswith("! demo/07") for t in texts)


def test_AC1_retry_command_from_needs_you_row(monkeypatch):
    _prep(monkeypatch)
    run = FakeRun(stdout=json.dumps(_doc()))
    screen = FakeScreen(["j", "j", "r", "q"])
    tui.loop(screen, "demo", run=run)
    cmds = [c for c, chk in run.calls[1:] if chk is False]
    assert ["watcher", "retry", "demo/07"] in cmds


def test_AC2_answer_appends_typed_line(monkeypatch):
    _prep(monkeypatch)
    run = FakeRun(stdout=json.dumps(_doc()))
    screen = FakeScreen(["j", "j", "a", "q"], typed=["go ahead"])
    tui.loop(screen, "demo", run=run)
    assert screen.echoed is True
    cmds = [c for c, chk in run.calls if chk is False]
    assert ["watcher", "answer", "demo/07", "go ahead"] in cmds


def test_command_output_shown_on_last_row(monkeypatch):
    _prep(monkeypatch)
    status = FakeRun(stdout=json.dumps(_doc()))
    out = FakeRun(stdout="retried demo/07\nmore")

    def run2(cmd, capture_output=False, text=False, check=True):
        if cmd[1:3] == ["status", "--json"]:
            return status(cmd, capture_output, text, check)
        return out(cmd, capture_output, text, check)

    screen = FakeScreen(["j", "j", "r", "q"])
    tui.loop(screen, "demo", run=run2)
    assert (23, "retried demo/07") in screen.drawn


def test_AC3_fetch_failure_shown_and_loop_continues(monkeypatch):
    _prep(monkeypatch)

    def run(cmd, capture_output=False, text=False, check=True):
        raise subprocess.CalledProcessError(1, cmd)

    screen = FakeScreen(["j", "q"])
    tui.loop(screen, "demo", run=run)
    assert any(t.startswith("status unavailable:") for _, t in screen.drawn)


def test_main_uses_curses_wrapper(monkeypatch):
    seen = []
    monkeypatch.setattr(tui.curses, "wrapper",
                        lambda fn, prd: seen.append((fn, prd)))
    assert tui.main("demo") == 0
    assert seen[0][1] == "demo"
    assert seen[0][0] is tui.loop


def test_cli_tui_subcommand(monkeypatch):
    seen = []
    monkeypatch.setattr(tui, "main", lambda prd: seen.append(prd) or 0)
    assert cli.main(["watcher", "tui", "--prd", "demo"]) == 0
    assert seen == ["demo"]


def test_key_timeout_redraws_instead_of_crashing(monkeypatch):
    import curses

    class TimeoutScreen(FakeScreen):
        def getkey(self):
            key = self.keys.pop(0) if self.keys else "q"
            if key is None:  # curses raises when no key arrives before the timeout
                raise curses.error("no input")
            return key

    _prep(monkeypatch)
    run = FakeRun(stdout=json.dumps(_doc()))
    screen = TimeoutScreen([None, None, "q"])
    tui.loop(screen, "demo", refresh=2.0, run=run)
    assert len(run.calls) >= 3  # fetched once per redraw


def test_zero_refresh_still_waits_for_keys(monkeypatch):
    _prep(monkeypatch)
    screen = FakeScreen(["q"])
    tui.loop(screen, "demo", refresh=0, run=FakeRun(stdout=json.dumps(_doc())))
    assert screen.timeouts[0] >= 100
