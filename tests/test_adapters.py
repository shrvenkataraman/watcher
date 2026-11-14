from hypothesis import given, settings, strategies as st

from watcher import hk, llm, omp, report
from watcher.adapters import (
    DesktopNotifier,
    HkGate,
    LlamaSwapServer,
    OmpAgent,
    default_adapters,
)
from watcher.ports import (
    Adapters,
    Agent,
    AgentResult,
    Gate,
    GateResult,
    ModelServer,
    Notifier,
)

OUTCOMES = st.sampled_from(["done", "question", "timeout", "error"])


def test_AC1_isinstance_protocols():
    assert isinstance(OmpAgent(), Agent)
    assert isinstance(HkGate(), Gate)
    assert isinstance(LlamaSwapServer(), ModelServer)
    assert isinstance(DesktopNotifier(), Notifier)


def test_AC1_options_kept():
    assert OmpAgent(a=1).options == {"a": 1}
    assert LlamaSwapServer().url == llm.BASE
    HkGate(x=1)
    DesktopNotifier(x=1)


def test_AC2_omp_question(monkeypatch):
    monkeypatch.setattr(omp, "run_omp", lambda *a, **k: omp.OmpResult("question", "q"))
    assert OmpAgent().run("r", "m", "/w", "p", "t") == AgentResult("question", "q")


@given(outcome=OUTCOMES, detail=st.text())
@settings(max_examples=30, deadline=None)
def test_AC2_property_omp_passthrough(outcome, detail):
    calls = []

    def fake(*a):
        calls.append(a)
        return omp.OmpResult(outcome, detail)

    orig = omp.run_omp
    omp.run_omp = fake
    try:
        r = OmpAgent().run("r", "m", "/w", "p", "t")
    finally:
        omp.run_omp = orig
    assert (r.outcome, r.detail) == (outcome, detail)
    assert calls == [("r", "m", "/w", "p", "t")]


@given(flag=st.booleans(), tail=st.text())
@settings(max_examples=30, deadline=None)
def test_AC3_property_verify_review_map(flag, tail):
    ov, orr = hk.verify, hk.review
    hk.verify = lambda w: hk.VerifyResult(flag, tail)
    hk.review = lambda w: hk.ReviewResult(flag, tail)
    try:
        assert HkGate().verify("/w") == GateResult(flag, tail)
        assert HkGate().review("/w") == GateResult(flag, tail)
    finally:
        hk.verify, hk.review = ov, orr


def test_AC3_lane_methods(monkeypatch):
    monkeypatch.setattr(hk, "lane_worktree", lambda root, prd, repo: f"{root}|{prd}|{repo}")
    monkeypatch.setattr(hk, "ensure_lane", lambda prd, repo, base, check, root: (prd, repo, base, check, root))
    g = HkGate()
    assert g.lane_worktree("r", "p", "x") == "r|p|x"
    assert g.ensure_lane("p", "x", "b", "c", "r") == ("p", "x", "b", "c", "r")


def test_AC4_llama_swap(monkeypatch):
    calls = []

    def rec(name, base=None):
        calls.append((name, base))
        return True

    monkeypatch.setattr(llm, "ensure_model", rec)
    assert LlamaSwapServer(url="http://x").ensure_model("m") is True
    assert calls == [("m", "http://x")]


def test_AC4_notifier(monkeypatch):
    calls = []
    monkeypatch.setattr(report, "notify", lambda t, b: calls.append((t, b)))
    assert DesktopNotifier().notify("t", "b") is None
    assert calls == [("t", "b")]


def test_AC5_default_adapters():
    a = default_adapters()
    assert isinstance(a, Adapters)
    assert isinstance(a.agent, OmpAgent)
    assert isinstance(a.gate, HkGate)
    assert isinstance(a.model_server, LlamaSwapServer)
    assert isinstance(a.notifier, DesktopNotifier)
