"""Model lease (multi-project ticket 01)."""
import os
import subprocess
import sys

import pytest
from hypothesis import given, settings, strategies as st

from watcher.lease import Lease, LeaseTimeout, lease_dir


def _fast(d):
    return Lease(str(d), sleep=lambda _s: None, poll=0)


def test_AC1_same_model_is_shared(tmp_path):
    a, b = _fast(tmp_path), _fast(tmp_path)
    a.acquire("a")
    b.acquire("a", timeout=0)
    assert (a.held(), b.held()) == ("a", "a")


def test_AC2_other_model_times_out(tmp_path):
    a, b = _fast(tmp_path), _fast(tmp_path)
    a.acquire("a")
    with pytest.raises(LeaseTimeout):
        b.acquire("b", timeout=0)
    assert b.held() is None


def test_AC3_release_frees_the_other_model(tmp_path):
    a, b = _fast(tmp_path), _fast(tmp_path)
    a.acquire("a")
    a.release()
    b.acquire("b", timeout=0)
    assert b.held() == "b"


def test_AC4_one_object_switches_model(tmp_path):
    a = _fast(tmp_path)
    a.acquire("a")
    a.acquire("b", timeout=0)
    assert a.held() == "b"


def test_AC5_held_none_and_double_release(tmp_path):
    a = _fast(tmp_path)
    assert a.held() is None
    a.acquire("a")
    a.release()
    a.release()
    assert a.held() is None


def test_AC6_crashed_process_frees_its_model(tmp_path):
    code = ("import os,sys\nfrom watcher.lease import Lease\n"
            "Lease(sys.argv[1]).acquire('a')\nos._exit(0)\n")
    subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=True)
    b = _fast(tmp_path)
    b.acquire("b", timeout=0)
    assert b.held() == "b"


def test_AC7_lease_dir_name():
    assert lease_dir("/x") == os.path.join("/x", "watcher-leases")


STEPS = st.lists(st.tuples(st.integers(0, 2), st.sampled_from(["a", "b", "rel"])), max_size=25)


@settings(max_examples=60, deadline=None)
@given(STEPS)
def test_AC2_property_never_two_models_at_once(tmp_path_factory, steps):
    d = tmp_path_factory.mktemp("lease")
    objs = [_fast(d) for _ in range(3)]
    held = [None, None, None]  # reference model
    for i, op in steps:
        if op == "rel":
            objs[i].release()
            held[i] = None
            continue
        others = {m for j, m in enumerate(held) if j != i and m}
        ok = not (others - {op})
        try:
            objs[i].acquire(op, timeout=0)
            assert ok
            held[i] = op
        except LeaseTimeout:
            assert not ok
            held[i] = None  # a failed switch released the old model first
        assert len({m for m in held if m}) <= 1
        assert [o.held() for o in objs] == held
    for o in objs:
        o.release()
