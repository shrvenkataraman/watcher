import tempfile
from pathlib import Path

from hypothesis import given, settings
from hypothesis import strategies as st

from watcher.agents import CommandAgent
from watcher.ports import Agent, AgentResult

TEXT = st.text(
    alphabet=st.characters(blacklist_categories=("Cs", "Cc")), min_size=0, max_size=20
)


def _run(argv, role="implement", model="m", wt=None, **kw):
    agent = CommandAgent(argv=argv, **kw)
    return agent.run(role, model, str(wt), "prompt.md", "do it")


def test_AC1_command_runs_in_worktree_and_is_done(tmp_path):
    r = _run(["sh", "-c", "echo {role} {model} > out.txt"], wt=tmp_path)
    assert r.outcome == "done"
    assert (tmp_path / "out.txt").read_text().strip() == "implement m"


@settings(max_examples=25, deadline=None)
@given(role=TEXT, model=TEXT)
def test_AC1_property_argv_substitutes_values(role, model):
    with tempfile.TemporaryDirectory() as d:
        template = ["sh", "-c", 'printf %s "$0" > out.txt', "{role}|{model}"]
        r = CommandAgent(argv=template).run(role, model, d, "p.md", "t")
        assert r.outcome == "done"
        assert (Path(d) / "out.txt").read_text() == f"{role}|{model}"


def test_AC2_question_file_returns_question(tmp_path):
    (tmp_path / ".agent").mkdir()
    r = _run(
        ["sh", "-c", "printf 'what now?' > .agent/question.md"], wt=tmp_path
    )
    assert r == AgentResult("question", "what now?")


def test_AC2_stale_question_file_is_deleted_first(tmp_path):
    (tmp_path / ".agent").mkdir()
    (tmp_path / ".agent" / "question.md").write_text("old")
    r = _run(["true"], wt=tmp_path)
    assert r.outcome == "done"
    assert not (tmp_path / ".agent" / "question.md").exists()


def test_AC3_nonzero_exit_is_error_with_tail(tmp_path):
    r = _run(["sh", "-c", "echo boom >&2; exit 3"], wt=tmp_path)
    assert r.outcome == "error"
    assert "boom" in r.detail


def test_AC3_timeout(tmp_path):
    r = _run(["sleep", "5"], wt=tmp_path, timeout=0.2)
    assert r.outcome == "timeout"


def test_AC3_detail_is_last_40_lines(tmp_path):
    r = _run(["sh", "-c", "seq 1 100"], wt=tmp_path)
    assert r.outcome == "done"
    assert r.detail.splitlines() == [str(n) for n in range(61, 101)]


def _tools(tmp_path, role):
    agent = CommandAgent(
        argv=["sh", "-c", "printf %s {tools} > t.txt"],
        edit_tools="EDIT",
        read_tools="READ",
    )
    agent.run(role, "m", str(tmp_path), "p.md", "t")
    return (tmp_path / "t.txt").read_text()


def test_AC4_tools_for_review_roles_is_read_tools(tmp_path):
    assert _tools(tmp_path, "review") == "READ"
    assert _tools(tmp_path, "pr_review") == "READ"


def test_AC4_tools_for_other_roles_is_edit_tools(tmp_path):
    for role in ("implement", "fix", "pr_fix"):
        assert _tools(tmp_path, role) == "EDIT"


def test_AC4_all_fields_expand(tmp_path):
    agent = CommandAgent(
        argv=["sh", "-c", 'printf "%s|%s|%s" "$0" "$1" "$2" > f.txt',
              "{prompt_file}", "{task}", "{worktree}"]
    )
    agent.run("implement", "m", str(tmp_path), "p.md", "T")
    assert (tmp_path / "f.txt").read_text() == f"p.md|T|{tmp_path}"


def test_AC5_is_an_agent():
    assert isinstance(CommandAgent(argv=["true"]), Agent)


def test_AC5_ignores_extra_options():
    assert isinstance(CommandAgent(argv=["true"], other=1), Agent)
