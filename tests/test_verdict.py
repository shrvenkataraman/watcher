"""Reviewer verdict parser (watcher ticket 12)."""
import json
import shutil
import tempfile

import pytest
from hypothesis import given, settings
import hypothesis.strategies as st

from watcher.verdict import BadVerdict, Verdict, parse_verdict

COMMIT = "abcdef1234567890"
FINDING = {"id": "f1", "file": "watcher/core.py", "symbol": "step", "ac": "AC2", "problem": "x"}


def _write(tmp_path, obj):
    path = tmp_path / "verdict.json"
    path.write_text(json.dumps(obj), encoding="utf-8")
    return str(path)


def _valid(approved=True, findings=None):
    return {"verdict": "APPROVED" if approved else "CHANGES", "commit": COMMIT,
            "findings": [] if findings is None else findings}


def test_AC1_valid_approved_file_is_approved(tmp_path):
    v = parse_verdict(_write(tmp_path, _valid()), COMMIT)
    assert isinstance(v, Verdict)
    assert v.approved is True
    assert v.findings_json == "[]"


def test_AC1_approved_with_findings_keeps_them(tmp_path):
    v = parse_verdict(_write(tmp_path, _valid(findings=[FINDING])), COMMIT)
    assert v.approved is True
    assert json.loads(v.findings_json) == [FINDING]


def test_AC2_valid_changes_file_round_trips_findings(tmp_path):
    v = parse_verdict(_write(tmp_path, _valid(approved=False, findings=[FINDING])), COMMIT)
    assert v.approved is False
    assert json.loads(v.findings_json) == [FINDING]


def test_AC2_commit_prefix_match_seven_or_more_is_valid(tmp_path):
    v = parse_verdict(_write(tmp_path, _valid(approved=False, findings=[FINDING])), COMMIT[:8])
    assert v.approved is False


def _finding_without(key):
    f = dict(FINDING)
    del f[key]
    return f


@pytest.mark.parametrize(
    "obj_or_missing, field",
    [
        ("__missing__", "file"),
        ({"verdict": "MAYBE", "commit": COMMIT, "findings": []}, "verdict"),
        ({"verdict": "APPROVED", "commit": "ffffeedd1122", "findings": []}, "commit"),
        ({"verdict": "APPROVED", "findings": []}, "commit"),
        ({"verdict": "APPROVED", "commit": 7, "findings": []}, "commit"),
        ({"verdict": "APPROVED", "commit": COMMIT}, "findings"),
        ({"verdict": "APPROVED", "commit": COMMIT, "findings": "x"}, "findings"),
        (_valid(approved=False, findings=[7]), "findings"),
        (_valid(approved=False, findings=[_finding_without("file")]), "file"),
        (_valid(approved=False, findings=[dict(FINDING, problem=7)]), "problem"),
        (_valid(approved=False, findings=[]), "findings"),
        ("not json at all", None),
    ],
)
def test_AC3_malformed_cases_raise_badverdict_naming_the_field(tmp_path, obj_or_missing, field):
    if obj_or_missing == "__missing__":
        path = str(tmp_path / "absent.json")
    elif obj_or_missing == "not json at all":
        path = str(tmp_path / "broken.json")
        open(path, "w").write("this is not json {{{")
    else:
        path = _write(tmp_path, obj_or_missing)
    with pytest.raises(BadVerdict) as exc:
        parse_verdict(path, COMMIT)
    if field is not None:
        assert field in str(exc.value)


def test_AC3_commit_argument_short_prefix_mismatch(tmp_path):
    # file holds an 8-char commit, caller passes a 6-char one: too short to prefix-match.
    v = _valid(approved=False, findings=[FINDING])
    v["commit"] = "abcdef12"
    with pytest.raises(BadVerdict, match="commit"):
        parse_verdict(_write(tmp_path, v), "abcdef")


def test_AC3_commit_argument_not_a_string_is_a_mismatch(tmp_path):
    with pytest.raises(BadVerdict, match="commit"):
        parse_verdict(_write(tmp_path, _valid()), 7)


def test_AC3_non_utf8_bytes_raise_badverdict_not_unicodeerror(tmp_path):
    path = tmp_path / "binary.json"
    path.write_bytes(b"\xff\xfe\x00garbage")
    with pytest.raises(BadVerdict):
        parse_verdict(str(path), COMMIT)


finding_st = st.fixed_dictionaries({
    "id": st.text(max_size=6), "file": st.text(max_size=12), "symbol": st.text(max_size=8),
    "ac": st.text(max_size=6), "problem": st.text(max_size=20),
})


@settings(deadline=None, max_examples=40)
@given(st.lists(finding_st, max_size=3))
def test_AC2_property_findings_round_trip_through_the_file(findings):
    tmp = tempfile.mkdtemp(prefix="verdict-")
    try:
        if not findings:
            findings = [FINDING]
        path = _write_path(tmp, {"verdict": "CHANGES", "commit": COMMIT, "findings": findings})
        v = parse_verdict(path, COMMIT)
        assert json.loads(v.findings_json) == findings
    finally:
        shutil.rmtree(tmp)


def _write_path(dirpath, obj):
    path = f"{dirpath}/verdict.json"
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(json.dumps(obj))
    return path


junk_st = st.one_of(
    st.none(), st.booleans(), st.integers(), st.text(max_size=30),
    st.lists(st.integers(), max_size=3),
    st.dictionaries(st.text(max_size=8), st.text(max_size=8), max_size=3),  # lacks the shape
)


@settings(deadline=None, max_examples=60)
@given(junk_st)
def test_AC3_property_junk_always_raises_badverdict(junk):
    tmp = tempfile.mkdtemp(prefix="verdict-")
    try:
        path = _write_path(tmp, junk)
        with pytest.raises(BadVerdict):
            parse_verdict(path, COMMIT)
    finally:
        shutil.rmtree(tmp)
