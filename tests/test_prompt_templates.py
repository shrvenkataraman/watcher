"""Prompt rule templates (watcher ticket 13). Golden strings were captured from the
prompt builders before any change."""
import os

from hypothesis import given, settings, strategies as st

from watcher import prompts
from watcher.executor import Ctx
from watcher.prompts import (EDIT_RULE, FIX_RULE, READ_RULE, REVIEW_RULE,
                             write_prompt)

EDIT = ("Edit only files in the ticket's Edit line. Do not edit .agent/ except "
        ".agent/question.md. Do not commit. If you cannot proceed without a decision, "
        "write the question to .agent/question.md and stop.")
FIX = EDIT + " Fix only these findings."
READ = ("Do not edit files. Write .agent/pr-verdict.json in the same verdict format "
        "with commit set to HEAD.")
REVIEW = ("Run git show abc123. Do not edit files. Write .agent/verdicts/03.json with keys "
          "verdict, commit, findings; each finding has id, file, symbol, ac, problem.")

GOLDEN = {
    "implement": ("# Role: implement\n\n## Ticket\nT\n\n## Previous failure\nF\n\n## Rules\n"
                  + EDIT + "\n", dict(ticket_file="t", failure="F")),
    "fix": ("# Role: fix\n\n## Ticket\nT\n\n## Findings\nX\n\n## Rules\n" + FIX + "\n",
            dict(ticket_file="t", findings="X")),
    "review": ("# Role: review\n\n## Ticket\nT\n\n## Commit\nabc123\n\n## Rules\n" + REVIEW + "\n",
               dict(ticket_file="t", commit="abc123")),
    "pr_review": ("# Role: pr_review\n\n## Spec\nS\n\n## Diff\nD\n\n## Verdicts\nV\n\n## Rules\n"
                  + READ + "\n", dict(spec_file="s", diff="D", verdicts="V")),
    "pr_fix": ("# Role: pr_fix\n\n## Spec\nS\n\n## Findings\nX\n\n## Rules\n" + FIX + "\n",
               dict(spec_file="s", findings="X")),
}
TPL = prompts.__file__.replace("prompts.py", "templates")


def _files(tmp_path):
    (tmp_path / "t").write_text("T")
    (tmp_path / "s").write_text("S")
    return str(tmp_path / "t"), str(tmp_path / "s")


def _kw(tmp_path, kw):
    t, s = _files(tmp_path)
    kw = dict(kw)
    if "ticket_file" in kw:
        kw["ticket_file"] = t
    if "spec_file" in kw:
        kw["spec_file"] = s
    return kw


def _rules_section(path):
    return open(path).read().split("## Rules\n", 1)[1]


def test_AC1_every_role_matches_golden_with_default_templates(tmp_path):
    for role, (want, kw) in GOLDEN.items():
        out = tmp_path / role
        path, _ = write_prompt(role, str(out), key="q/03", templates="", **_kw(tmp_path, kw))
        assert open(path).read() == want, role


def test_AC1_templates_dir_exists_with_all_roles():
    for role in GOLDEN:
        assert os.path.isfile(os.path.join(TPL, role + ".md")), role


def test_AC2_custom_template_replaces_only_that_role(tmp_path):
    tdir = tmp_path / "tpl"
    tdir.mkdir()
    (tdir / "implement.md").write_text("Custom rule.")
    kw = _kw(tmp_path, GOLDEN["implement"][1])
    path, _ = write_prompt("implement", str(tmp_path / "o"), key="q/03", templates=str(tdir), **kw)
    assert _rules_section(path) == "Custom rule.\n"
    want, kw2 = GOLDEN["fix"]
    path2, _ = write_prompt("fix", str(tmp_path / "o2"), key="q/03", templates=str(tdir),
                            **_kw(tmp_path, kw2))
    assert open(path2).read() == want


def test_AC2_custom_review_template_formats_placeholders(tmp_path):
    tdir = tmp_path / "tpl"
    tdir.mkdir()
    (tdir / "review.md").write_text("Look at {commit} then write {verdict_file}.\n")
    path, _ = write_prompt("review", str(tmp_path / "o"), key="q/03", commit="abc123",
                           ticket_file=_files(tmp_path)[0], templates=str(tdir))
    assert _rules_section(path) == "Look at abc123 then write .agent/verdicts/03.json.\n"


def test_AC2_missing_dir_falls_back_to_builtin(tmp_path):
    want, kw = GOLDEN["pr_fix"]
    path, _ = write_prompt("pr_fix", str(tmp_path / "o"), key="q/03",
                           templates=str(tmp_path / "nope"), **_kw(tmp_path, kw))
    assert open(path).read() == want


def test_AC2_ctx_has_templates_field_default_empty():
    assert Ctx.__dataclass_fields__["templates"].default == ""


@settings(max_examples=40, deadline=None)
@given(st.text(alphabet=st.characters(blacklist_characters="{}\r", blacklist_categories=("Cs",)),
               min_size=1).filter(lambda s: s.strip("\n") == s and s.strip() != ""))
def test_AC2_property_rules_section_equals_template_text(text):
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        tdir = os.path.join(d, "tpl")
        os.makedirs(tdir)
        with open(os.path.join(tdir, "pr_review.md"), "w", encoding="utf-8", newline="") as fh:
            fh.write(text + "\n")
        path, _ = write_prompt("pr_review", os.path.join(d, "o"), key="q/03", templates=tdir)
        with open(path, encoding="utf-8", newline="") as fh:
            assert fh.read().split("## Rules\n", 1)[1] == text + "\n"


def test_AC3_template_files_equal_constants():
    want = {"implement": EDIT_RULE, "fix": FIX_RULE, "review": REVIEW_RULE,
            "pr_review": READ_RULE, "pr_fix": FIX_RULE}
    for role, const in want.items():
        with open(os.path.join(TPL, role + ".md"), encoding="utf-8") as fh:
            assert fh.read() == const + "\n", role
