"""Prompt writer: role files with ordered non-empty sections (watcher ticket 15)."""
import os

from watcher.prompts import write_prompt


def _text(path):
    with open(path) as fh:
        return fh.read()


def _ticket(tmp_path, body="TICKET BODY"):
    p = tmp_path / "ticket.md"
    p.write_text(body)
    return str(p)


def _spec(tmp_path, body="SPEC BODY"):
    p = tmp_path / "spec.md"
    p.write_text(body)
    return str(p)


def test_AC1_implement_file_task_and_sections(tmp_path):
    out = str(tmp_path / "prompts")
    path, task = write_prompt("implement", out, ticket_file=_ticket(tmp_path),
                              failure="FAILED test_x", key="quark-kit/03")
    assert os.path.basename(path) == "implement-quark-kit_03.md"
    assert task == "Implement the ticket now."
    text = _text(path)
    assert text.startswith("# Role: implement")
    assert "## Ticket" in text and "TICKET BODY" in text
    assert "## Previous failure" in text and "FAILED test_x" in text
    assert "Edit only files in the ticket's Edit line. Do not edit .agent/ except .agent/question.md. Do not commit." in text
    assert "## Findings" not in text and "## Commit" not in text


def test_AC3_implement_names_the_question_file_rule(tmp_path):
    path, _ = write_prompt("implement", str(tmp_path), ticket_file=_ticket(tmp_path),
                           key="a/01")
    assert ".agent/question.md" in _text(path)


def test_AC1_implement_omits_empty_sections(tmp_path):
    path, _ = write_prompt("implement", str(tmp_path), ticket_file=_ticket(tmp_path),
                           key="a/01")
    assert "## Previous failure" not in _text(path)


def test_AC1_fix_file(tmp_path):
    path, task = write_prompt("fix", str(tmp_path), ticket_file=_ticket(tmp_path),
                              findings='[{"id":"f1"}]', key="quark-kit/02")
    assert os.path.basename(path) == "fix-quark-kit_02.md"
    assert task == "Fix the findings now."
    text = _text(path)
    assert text.startswith("# Role: fix")
    assert "## Ticket" in text
    assert "## Findings" in text and "f1" in text
    assert "Fix only these findings." in text


def test_AC1_AC2_review_file(tmp_path):
    path, task = write_prompt("review", str(tmp_path), ticket_file=_ticket(tmp_path),
                              commit="abc1234", key="quark-kit/03")
    assert os.path.basename(path) == "review-quark-kit_03.md"
    assert task == "Review the commit now."
    text = _text(path)
    assert ".agent/verdicts/03.json" in text
    assert "Run git show abc1234." in text
    assert "Do not edit files." in text
    assert "id, file, symbol, ac, problem" in text
    assert "## Previous failure" not in text


def test_AC1_pr_review_file(tmp_path):
    path, task = write_prompt("pr_review", str(tmp_path), spec_file=_spec(tmp_path),
                              diff="DIFF TEXT", verdicts='{"verdict":"REJECT"}',
                              key="quark-kit/04")
    assert os.path.basename(path) == "pr_review-quark-kit_04.md"
    assert task == "Review the PR now."
    text = _text(path)
    assert text.startswith("# Role: pr_review")
    for heading in ("## Spec", "## Diff", "## Verdicts"):
        assert heading in text
    assert text.index("## Spec") < text.index("## Diff") < text.index("## Verdicts")
    assert ".agent/pr-verdict.json" in text and "commit set to HEAD" in text


def test_AC1_pr_fix_file(tmp_path):
    path, task = write_prompt("pr_fix", str(tmp_path), spec_file=_spec(tmp_path),
                              findings='[{"id":"f9"}]', key="quark-kit/04")
    assert task == "Fix the PR findings now."
    text = _text(path)
    assert "## Spec" in text and "## Findings" in text
    assert "Fix only these findings." in text
    assert "## Ticket" not in text


def test_AC1_property_headings_keep_their_order(tmp_path):
    # every non-empty combination keeps the stated heading order per role
    cases = {
        "implement": (["## Ticket", "## Previous failure"],
                      {"ticket_file": _ticket(tmp_path), "failure": "x"}),
        "fix": (["## Ticket", "## Findings"],
                {"ticket_file": _ticket(tmp_path), "findings": "f"}),
        "review": (["## Ticket", "## Commit"],
                   {"ticket_file": _ticket(tmp_path), "commit": "c"}),
        "pr_review": (["## Spec", "## Diff", "## Verdicts"],
                      {"spec_file": _spec(tmp_path), "diff": "d", "verdicts": "v"}),
        "pr_fix": (["## Spec", "## Findings"],
                   {"spec_file": _spec(tmp_path), "findings": "f"}),
    }
    for role, (headings, full) in cases.items():
        for drop in range(len(headings)):
            args = dict(full)
            keys = list(full)
            if drop < len(keys):
                args[keys[drop]] = ""
            path, _ = write_prompt(role, str(tmp_path), key="r/01", **args)
            text = _text(path)
            present = [h for h in headings if h in text]
            idx = [text.index(h) for h in present]
            assert idx == sorted(idx), (role, present)
