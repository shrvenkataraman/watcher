"""Global queue order for the lease (multi-project ticket 13)."""
import json
import os

import pytest
from hypothesis import given, settings, strategies as st

from watcher.lease import Lease, LeaseTimeout, clear, publish, totals

ROLES = ("working", "review", "pr")


def _l(d):
    return Lease(str(d), sleep=lambda _s: None, poll=0)


def _ok(d, model, role):
    l = _l(d)
    l.acquire(model, timeout=0, role=role)
    return l


def _set(d, **c):
    publish(str(d), "p", {k: c.get(k, 0) for k in ROLES})


def test_AC1_publish_totals_clear(tmp_path):
    publish(str(tmp_path), "a", {"working": 1, "review": 2})
    publish(str(tmp_path), "b", {"working": 3})
    assert totals(str(tmp_path)) == {"working": 4, "review": 2, "pr": 0}
    clear(str(tmp_path), "a")
    clear(str(tmp_path), "nobody")
    assert totals(str(tmp_path))["working"] == 3


def test_AC2_working_blocks_review(tmp_path):
    _set(tmp_path, working=1, review=1)
    with pytest.raises(LeaseTimeout):
        _l(tmp_path).acquire("r", timeout=0, role="review")
    assert _ok(tmp_path, "f", "working").held() == "f"


def test_AC3_review_blocks_pr(tmp_path):
    _set(tmp_path, review=1, pr=1)
    with pytest.raises(LeaseTimeout):
        _l(tmp_path).acquire("g", timeout=0, role="pr")
    assert _ok(tmp_path, "r", "review").held() == "r"


def test_AC4_loaded_role_keeps_the_model(tmp_path):
    _set(tmp_path, review=1)
    _ok(tmp_path, "r", "review").release()
    _set(tmp_path, working=2, review=1)
    with pytest.raises(LeaseTimeout):
        _l(tmp_path).acquire("f", timeout=0, role="working")
    assert _ok(tmp_path, "r", "review").held() == "r"


def test_AC5_switch_after_queue_empties(tmp_path):
    _set(tmp_path, review=1)
    _ok(tmp_path, "r", "review").release()
    _set(tmp_path, working=2)
    assert _ok(tmp_path, "f", "working").held() == "f"


def test_AC6_empty_queues_allow_any_role(tmp_path):
    for role in ROLES:
        assert _ok(tmp_path, role, role).held() == role


def test_AC7_corrupt_wants_file_is_zero(tmp_path):
    _set(tmp_path, working=1)
    wants = os.path.join(str(tmp_path), "watcher-leases", "wants")
    d = wants if os.path.isdir(wants) else os.path.join(str(tmp_path), "wants")
    with open(os.path.join(d, "bad.json"), "w") as f:
        f.write("{not json")
    assert totals(str(tmp_path))["working"] == 1


def test_AC8_working_run_never_blocks_itself_and_review_waits(tmp_path):
    _set(tmp_path, working=5, review=1)
    for _ in range(50):
        _ok(tmp_path, "f", "working").release()
        with pytest.raises(LeaseTimeout):
            _l(tmp_path).acquire("r", timeout=0, role="review")


def _expect(cur, t, role):
    if cur and t[cur] > 0:
        return role == cur
    want = next((r for r in ROLES if t[r] > 0), None)
    return want is None or role == want


@settings(max_examples=60, deadline=None)
@given(cur=st.sampled_from((None,) + ROLES),
       counts=st.tuples(*[st.integers(0, 2)] * 3),
       role=st.sampled_from(ROLES))
def test_AC2_property_grant_rule(tmp_path_factory, cur, counts, role):
    d = tmp_path_factory.mktemp("g")
    if cur:
        _ok(d, cur, cur).release()
    t = dict(zip(ROLES, counts))
    publish(str(d), "p", t)
    try:
        _l(d).acquire(role, timeout=0, role=role)
        granted = True
    except LeaseTimeout:
        granted = False
    assert granted == _expect(cur, t, role)
