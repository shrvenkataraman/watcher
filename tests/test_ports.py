import dataclasses

import pytest

from watcher.ports import (
    Adapters,
    Agent,
    AgentResult,
    Gate,
    GateResult,
    ModelServer,
    Notifier,
)


class FakeAgent:
    def run(self, role, model, worktree, prompt_file, task):
        return AgentResult("done", "")


class FakeGate:
    def lane_worktree(self, root, prd, repo):
        return ""

    def ensure_lane(self, prd, repo, base, check, root):
        return ""

    def verify(self, worktree):
        return GateResult(True, "")

    def review(self, worktree):
        return GateResult(True, "")


class FakeServer:
    def ensure_model(self, name):
        return True


class FakeNotifier:
    def notify(self, title, body):
        return None


def test_AC1_plain_classes_satisfy_protocols():
    assert isinstance(FakeAgent(), Agent)
    assert isinstance(FakeGate(), Gate)
    assert isinstance(FakeServer(), ModelServer)
    assert isinstance(FakeNotifier(), Notifier)


def test_AC2_missing_method_fails_isinstance():
    class BadAgent: ...

    class BadGate:
        def lane_worktree(self, root, prd, repo): ...
        def ensure_lane(self, prd, repo, base, check, root): ...
        def verify(self, worktree): ...

    class BadServer: ...

    class BadNotifier: ...

    assert not isinstance(BadAgent(), Agent)
    assert not isinstance(BadGate(), Gate)
    assert not isinstance(BadServer(), ModelServer)
    assert not isinstance(BadNotifier(), Notifier)


def test_AC3_adapters_holds_four_and_is_frozen():
    a, g, m, n = FakeAgent(), FakeGate(), FakeServer(), FakeNotifier()
    ad = Adapters(a, g, m, n)
    assert (ad.agent, ad.gate, ad.model_server, ad.notifier) == (a, g, m, n)
    with pytest.raises(dataclasses.FrozenInstanceError):
        ad.agent = FakeAgent()


def test_AC4_results_are_frozen_dataclasses():
    r = AgentResult("done", "x")
    g = GateResult(True, "t")
    assert [f.name for f in dataclasses.fields(AgentResult)] == ["outcome", "detail"]
    assert [f.name for f in dataclasses.fields(GateResult)] == ["ok", "tail"]
    assert (r.outcome, r.detail, g.ok, g.tail) == ("done", "x", True, "t")
    with pytest.raises(dataclasses.FrozenInstanceError):
        r.outcome = "error"
    with pytest.raises(dataclasses.FrozenInstanceError):
        g.ok = False
