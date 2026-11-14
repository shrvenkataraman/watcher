"""Red tests for ticket 19: watcher new builds an inbox from a ticket bundle."""

import os

import pytest
from hypothesis import given, settings, strategies as st

from watcher.inbox import load_inbox


def _bundle(root, blocked):
    """blocked: {nn: [nn,...]}; writes spec.md and issues/NN-t.md."""
    os.makedirs(os.path.join(root, "issues"), exist_ok=True)
    with open(os.path.join(root, "spec.md"), "w") as f:
        f.write("# spec\n")
    for nn, deps in blocked.items():
        line = ", ".join(f"{d:02d}" for d in deps) if deps else "None"
        with open(os.path.join(root, "issues", f"{nn:02d}-t.md"), "w") as f:
            f.write(f"# {nn}\n\n**Status:** ready\n**Blocked by:** {line}\n")


def _build(bundle, out, **kw):
    from watcher.newinbox import build_inbox

    return build_inbox(str(bundle), "R", "prd1", "true", str(out), **kw)


def test_AC1_builds_loadable_inbox(tmp_path):
    _bundle(tmp_path / "b", {1: [], 2: [1]})
    path = _build(tmp_path / "b", tmp_path / "out")
    assert path == os.path.join(str(tmp_path / "out"), "prd1")
    plan = load_inbox(path)
    tickets = {t.key: t for lane in plan.state.lanes for t in lane.tickets}
    assert sorted(tickets) == ["R/01", "R/02"]
    assert tickets["R/02"].depends_on == ("R/01",)
    assert tickets["R/01"].depends_on == ()


def test_AC2_second_build_raises_and_keeps_first(tmp_path):
    _bundle(tmp_path / "b", {1: []})
    path = _build(tmp_path / "b", tmp_path / "out")
    mpath = os.path.join(path, "manifest.json")
    before = open(mpath).read()
    with pytest.raises(FileExistsError):
        _build(tmp_path / "b", tmp_path / "out")
    assert open(mpath).read() == before


def test_AC3_cli_prints_path_exit_0(tmp_path, capsys):
    from watcher.cli import main

    _bundle(tmp_path / "b", {1: []})
    rc = main(["new", "--from", str(tmp_path / "b"), "--repo", "R", "--prd", "prd1",
               "--check", "true", "--inbox-root", str(tmp_path / "out")])
    assert rc == 0
    assert capsys.readouterr().out.strip() == os.path.join(str(tmp_path / "out"), "prd1")


def test_AC4_unknown_blocker_raises_valueerror(tmp_path):
    _bundle(tmp_path / "b", {1: [], 2: [7]})
    with pytest.raises(ValueError, match="07|7"):
        _build(tmp_path / "b", tmp_path / "out")


@st.composite
def dags(draw):
    n = draw(st.integers(1, 8))
    return {i: draw(st.lists(st.integers(1, i - 1), unique=True, max_size=3)) if i > 1 else []
            for i in range(1, n + 1)}


@settings(max_examples=40, deadline=None)
@given(dag=dags(), bs=st.integers(1, 6))
def test_AC1_property_roundtrip_edges(tmp_path_factory, dag, bs):
    base = tmp_path_factory.mktemp("p")
    _bundle(str(base / "b"), dag)
    path = _build(base / "b", base / "out", batch_size=bs)
    plan = load_inbox(path)
    got = {t.key: set(t.depends_on) for lane in plan.state.lanes for t in lane.tickets}
    want = {f"R/{k:02d}": {f"R/{d:02d}" for d in v} for k, v in dag.items()}
    assert got == want
