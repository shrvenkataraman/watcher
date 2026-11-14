"""omp worker runner against fake omp scripts (watcher ticket 11)."""
import os
import stat

import pytest

from watcher.omp import OmpResult, TOOLS, build_argv, run_omp

FAKE = os.path.join(os.path.dirname(__file__), "fakes", "bin", "omp")


@pytest.fixture
def fake_omp(tmp_path, monkeypatch):
    os.chmod(FAKE, os.stat(FAKE).st_mode | stat.S_IEXEC)
    log = tmp_path / "omp.log"
    monkeypatch.setenv("OMP_LOG", str(log))
    monkeypatch.setenv("WATCHER_OMP", FAKE)
    wt = tmp_path / "wt"
    (wt / ".agent").mkdir(parents=True)
    return str(wt), log


def test_AC1_argv_for_review():
    argv = build_argv("review", "qwen3.8-27b-w8a8", "/tmp/p.md", "Review the commit now.")
    assert argv[:2] == ["omp", "-p"] or argv[1] == "-p"  # binary name may be overridden by env
    assert "--tools" in argv and argv[argv.index("--tools") + 1] == "read,grep,find,ls"
    assert "--thinking" in argv and argv[argv.index("--thinking") + 1] == "medium"
    assert argv[-2] == "@ /tmp/p.md".strip() or argv[-2] == "@/tmp/p.md"
    assert argv[-1] == "Review the commit now."


def test_property_read_only_roles_never_get_write_tools():
    for role in ("review", "pr_review"):
        argv = build_argv(role, "m", "p.md", "t")
        tools = argv[argv.index("--tools") + 1]
        for banned in ("edit", "write", "bash"):
            assert banned not in tools.split(",")


def test_AC2_question_file_gives_question_outcome(fake_omp, monkeypatch):
    wt, _ = fake_omp
    monkeypatch.setenv("FAKE_OMP_MODE", "question")
    res = run_omp("implement", "qwen3.8-flash-next", wt, "p.md", "Implement now.", timeout=30)
    assert isinstance(res, OmpResult)
    assert res.outcome == "question"
    assert res.detail == "Which base branch should I use?\n"


def test_AC3_slow_omp_gives_timeout(fake_omp, monkeypatch):
    wt, _ = fake_omp
    monkeypatch.setenv("FAKE_OMP_MODE", "sleep")
    monkeypatch.setenv("FAKE_OMP_SLEEP", "5")
    res = run_omp("implement", "m", wt, "p.md", "t", timeout=0.5)
    assert res.outcome == "timeout"


def test_AC4_zero_exit_with_stopReason_error_gives_error(fake_omp, monkeypatch):
    wt, _ = fake_omp
    monkeypatch.setenv("FAKE_OMP_MODE", "stoperror")
    res = run_omp("fix", "m", wt, "p.md", "t", timeout=30)
    assert res.outcome == "error"


def test_AC5_stale_question_file_is_deleted_before_the_run(fake_omp, monkeypatch):
    wt, _ = fake_omp
    stale = os.path.join(wt, ".agent", "question.md")
    with open(stale, "w") as fh:
        fh.write("stale question from last time\n")
    monkeypatch.setenv("FAKE_OMP_MODE", "ok")
    res = run_omp("implement", "m", wt, "p.md", "t", timeout=30)
    assert res.outcome == "done"
    assert not os.path.exists(stale)


def test_nonzero_exit_gives_error(fake_omp, monkeypatch):
    wt, _ = fake_omp
    monkeypatch.setenv("FAKE_OMP_MODE", "fail")
    res = run_omp("implement", "m", wt, "p.md", "t", timeout=30)
    assert res.outcome == "error"
    assert "omp crashed" in res.detail
