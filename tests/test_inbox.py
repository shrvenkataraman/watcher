"""Inbox loader: manifest validation and initial State (watcher ticket 02)."""
import json
import os

import pytest

from watcher.inbox import InboxError, Plan, load_inbox
from watcher.types import State

GOOD_MANIFEST = {
    "prd": "earnings-q4",
    "base": "develop",
    "batch_size": 2,
    "repos": {
        "quark-kit": {"spec": "specs/quark-kit.md", "depends_on": {"02": ["qresearch/01"]}},
        "qresearch": {"spec": "specs/qresearch.md"},
    },
}
GOOD_FILES = {
    "specs/quark-kit.md": "# quark kit spec",
    "specs/qresearch.md": "# qresearch spec",
    "tickets/quark-kit/01-a.md": "t",
    "tickets/quark-kit/02-b.md": "t",
    "tickets/quark-kit/03-c.md": "t",
    "tickets/qresearch/01-x.md": "t",
}


def _inbox(tmp_path, manifest=None, files=None, drop_manifest=False, name="inbox") -> str:
    root = tmp_path / name
    root.mkdir()
    if not drop_manifest:
        (root / "manifest.json").write_text(json.dumps(manifest if manifest is not None else GOOD_MANIFEST))
    for rel, body in (files if files is not None else GOOD_FILES).items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body)
    return str(root)


def test_AC1_valid_inbox_gives_lanes_batches_and_dependencies(tmp_path):
    plan = load_inbox(_inbox(tmp_path))
    assert isinstance(plan, Plan)
    assert plan.base == "develop" and plan.batch_size == 2
    s = plan.state
    assert isinstance(s, State) and s.prd == "earnings-q4"
    assert [lane.repo for lane in s.lanes] == ["qresearch", "quark-kit"]  # sorted by repo name
    qk = next(l for l in s.lanes if l.repo == "quark-kit")
    assert [t.key for t in qk.tickets] == ["quark-kit/01", "quark-kit/02", "quark-kit/03"]  # NN order
    assert [t.batch for t in qk.tickets] == [0, 0, 1]  # index // batch_size
    assert all(t.status == "pending" for lane in s.lanes for t in lane.tickets)
    assert next(t for t in qk.tickets if t.key == "quark-kit/02").depends_on == ("qresearch/01",)
    assert plan.specs["quark-kit"] == os.path.join(str(tmp_path), "inbox", "specs", "quark-kit.md")
    assert plan.ticket_files["qresearch/01"] == os.path.join(
        str(tmp_path), "inbox", "tickets", "qresearch", "01-x.md")


def test_AC1_property_counts_unique_keys_and_dependency_batches(tmp_path):
    plan = load_inbox(_inbox(tmp_path))
    tickets = [t for lane in plan.state.lanes for t in lane.tickets]
    keys = [t.key for t in tickets]
    assert len(keys) == len(set(keys)) == len(GOOD_FILES) - 2  # two spec files are not tickets
    by_key = {t.key: t for t in tickets}
    for t in tickets:
        for dep in t.depends_on:
            assert by_key[dep].batch <= t.batch


def test_AC2_missing_manifest_raises(tmp_path):
    with pytest.raises(InboxError, match="manifest"):
        load_inbox(_inbox(tmp_path, drop_manifest=True))


def test_AC2_repo_without_tickets_raises(tmp_path):
    files = {k: v for k, v in GOOD_FILES.items() if not k.startswith("tickets/qresearch/")}
    with pytest.raises(InboxError, match="qresearch"):
        load_inbox(_inbox(tmp_path, files=files))


def test_AC2_missing_spec_file_raises(tmp_path):
    files = {k: v for k, v in GOOD_FILES.items() if k != "specs/qresearch.md"}
    with pytest.raises(InboxError, match="qresearch"):
        load_inbox(_inbox(tmp_path, files=files))


def test_AC2_depends_on_key_not_a_ticket_raises(tmp_path):
    m = json.loads(json.dumps(GOOD_MANIFEST))
    m["repos"]["quark-kit"]["depends_on"] = {"99": ["qresearch/01"]}
    with pytest.raises(InboxError, match="quark-kit/99"):
        load_inbox(_inbox(tmp_path, manifest=m))


def test_AC2_depends_on_target_not_a_ticket_raises(tmp_path):
    m = json.loads(json.dumps(GOOD_MANIFEST))
    m["repos"]["quark-kit"]["depends_on"] = {"02": ["qresearch/77"]}
    with pytest.raises(InboxError, match="qresearch/77"):
        load_inbox(_inbox(tmp_path, manifest=m))


def test_AC2_cycle_raises(tmp_path):
    m = json.loads(json.dumps(GOOD_MANIFEST))
    m["repos"]["quark-kit"]["depends_on"] = {"01": ["qresearch/01"]}
    m["repos"]["qresearch"]["depends_on"] = {"01": ["quark-kit/01"]}
    with pytest.raises(InboxError, match="cycle"):
        load_inbox(_inbox(tmp_path, manifest=m))


def test_AC2_dependency_in_a_later_batch_raises(tmp_path):
    # quark-kit/01 (batch 0) depends on qresearch/03 (index 2, batch 1): impossible to approve in time.
    m = json.loads(json.dumps(GOOD_MANIFEST))
    m["repos"]["quark-kit"]["depends_on"] = {"01": ["qresearch/03"]}
    files = dict(GOOD_FILES, **{"tickets/qresearch/02-y.md": "t", "tickets/qresearch/03-z.md": "t"})
    with pytest.raises(InboxError, match="qresearch/03"):
        load_inbox(_inbox(tmp_path, manifest=m, files=files))


def test_AC2_batch_size_below_one_raises(tmp_path):
    m = json.loads(json.dumps(GOOD_MANIFEST))
    m["batch_size"] = 0
    with pytest.raises(InboxError, match="batch_size"):
        load_inbox(_inbox(tmp_path, manifest=m))


def test_AC3_absent_batch_size_means_five(tmp_path):
    m = json.loads(json.dumps(GOOD_MANIFEST))
    del m["batch_size"]
    plan = load_inbox(_inbox(tmp_path, manifest=m))
    assert plan.batch_size == 5
    qk = next(l for l in plan.state.lanes if l.repo == "quark-kit")
    assert [t.batch for t in qk.tickets] == [0, 0, 0]
