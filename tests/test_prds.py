"""watcher prds (multi-project ticket 03)."""
import json
import os

from hypothesis import given, settings, strategies as st

from watcher import cli, store


def _mk(root, name, with_state=True):
    d = os.path.join(root, "watcher", name)
    os.makedirs(d)
    if with_state:
        open(os.path.join(d, "state.json"), "w").write("{}")


def test_AC1_lists_sorted_prds(tmp_path):
    _mk(str(tmp_path), "b")
    _mk(str(tmp_path), "a")
    assert store.list_prds(str(tmp_path)) == ["a", "b"]


def test_AC2_folder_without_state_is_left_out(tmp_path):
    _mk(str(tmp_path), "a")
    _mk(str(tmp_path), "empty", with_state=False)
    assert store.list_prds(str(tmp_path)) == ["a"]


def test_AC3_missing_root_gives_empty(tmp_path):
    assert store.list_prds(str(tmp_path / "nope")) == []


def test_AC4_command_prints_json(tmp_path, capsys):
    _mk(str(tmp_path), "a")
    _mk(str(tmp_path), "b")
    assert cli.main(["prds", "--state-root", str(tmp_path)]) == 0
    assert json.loads(capsys.readouterr().out) == {"schema": 1, "prds": ["a", "b"]}


def test_AC5_empty_root_prints_empty_list(tmp_path, capsys):
    assert cli.main(["prds", "--state-root", str(tmp_path)]) == 0
    assert capsys.readouterr().out.strip() == '{"schema": 1, "prds": []}'


def test_AC6_readme_names_prds():
    import pathlib
    readme = pathlib.Path(__file__).resolve().parent.parent / "README.md"
    assert "watcher prds" in readme.read_text(encoding="utf-8")


@settings(max_examples=30, deadline=None)
@given(st.sets(st.from_regex(r"[a-z][a-z0-9-]{0,6}", fullmatch=True), max_size=6))
def test_AC1_property_sorted_and_unique(tmp_path_factory, names):
    root = str(tmp_path_factory.mktemp("r"))
    for n in names:
        _mk(root, n)
    got = store.list_prds(root)
    assert got == sorted(names) and len(got) == len(set(got))
