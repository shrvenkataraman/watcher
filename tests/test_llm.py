"""llama-swap adapter against a fake server (watcher ticket 10)."""
import time

import pytest

from tests.fakes.llama_swap import FakeLlamaSwap
from watcher import llm

FLASH = "qwen3.8-flash-next"
W8A8 = "qwen3.8-27b-w8a8"

noop = lambda *_a, **_k: None


def _clock():
    t = [0.0]
    def clock():
        return t[0]
    def advance(seconds):
        t[0] += seconds
    return clock, advance


def _sleep(advance_fn, step=10.0):
    def s(seconds):
        advance_fn(step)
    return s


def test_AC1_loaded_other_model_gets_unloaded_then_true():
    fake = FakeLlamaSwap(running_script=[
        [{"model": W8A8, "state": "ready"}],        # first /running: 27B loaded
        [{"model": W8A8, "state": "ready"}],        # during unload wait
        [{"model": FLASH, "state": "ready"}],       # after probe triggers load
    ])
    try:
        clock, adv = _clock()
        assert llm.ensure_model(FLASH, base=fake.base, poll=10, sleep=_sleep(adv), clock=clock) is True
        assert fake.unloads == [W8A8]
    finally:
        fake.stop()


def test_AC2_target_already_only_ready_model_no_unload():
    fake = FakeLlamaSwap(running_script=[[{"model": FLASH, "state": "ready"}]])
    try:
        clock, adv = _clock()
        assert llm.ensure_model(FLASH, base=fake.base, poll=10, sleep=_sleep(adv), clock=clock) is True
        assert fake.unloads == []
    finally:
        fake.stop()


def test_AC3_never_ready_gives_false_after_deadline():
    fake = FakeLlamaSwap(running_script=[[{"model": "other-model", "state": "ready"}]])
    try:
        clock, adv = _clock()
        # load_timeout 100 s; each sleep advances 10 s -> the deadline passes long before ready.
        assert llm.ensure_model(FLASH, base=fake.base, load_timeout=100, poll=10,
                                sleep=_sleep(adv), clock=clock) is False
    finally:
        fake.stop()


def test_AC4_dead_server_gives_false_no_exception():
    fake = FakeLlamaSwap(refuse=True)  # never listens; connections are refused
    clock, adv = _clock()
    assert llm.ensure_model(FLASH, base="http://127.0.0.1:1", load_timeout=10, poll=1,
                            sleep=_sleep(adv), clock=clock) is False


def test_AC1_running_parses_model_and_state():
    fake = FakeLlamaSwap(running_script=[[{"model": W8A8, "state": "loading"},
                                          {"model": FLASH, "state": "ready"}]])
    try:
        assert llm.running(base=fake.base) == [(W8A8, "loading"), (FLASH, "ready")]
    finally:
        fake.stop()


def test_probe_true_on_200_with_choices_false_on_500():
    ok = FakeLlamaSwap()
    bad = FakeLlamaSwap(completion_status=500)
    try:
        assert llm.probe(FLASH, base=ok.base) is True
        assert llm.probe(FLASH, base=bad.base) is False
    finally:
        ok.stop()
        bad.stop()


@pytest.mark.parametrize("status,refuse", [(200, False), (500, False), (200, True)])
def test_AC4_returns_bool_for_every_server_behaviour(status, refuse):
    fake = FakeLlamaSwap(running_script=[[{"model": "x", "state": "ready"}]],
                         completion_status=status, refuse=refuse)
    clock, adv = _clock()
    base = fake.base if not refuse else "http://127.0.0.1:1"
    result = llm.ensure_model(FLASH, base=base, load_timeout=50, poll=10,
                              sleep=_sleep(adv), clock=clock)
    assert isinstance(result, bool)
    if not refuse:
        fake.stop()
