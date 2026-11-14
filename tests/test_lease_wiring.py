"""Lease wired into the executor and the loop (multi-project ticket 02)."""
import pytest

import watcher.executor as exmod
import watcher.lease as leasemod
from tests.test_executor_adapters import FakeServer, _make
from tests.test_loop import world  # noqa: F401  (fixture)
from watcher.executor import Ctx, execute
from watcher.loop import tick
from watcher.types import Action


class FakeLease:
    def __init__(self, order, fail=False):
        self.order, self.fail, self.acquired, self.released = order, fail, [], 0

    def acquire(self, model, timeout=0):
        self.order.append("acquire")
        if self.fail:
            raise leasemod.LeaseTimeout(model)
        self.acquired.append(model)

    def release(self):
        self.released += 1


class OrderServer(FakeServer):
    def __init__(self, order):
        super().__init__(True)
        self.order = order

    def ensure_model(self, name):
        self.order.append("ensure")
        return super().ensure_model(name)


def _ctx_with(tmp_path, lease, server):
    ctx, _ = _make(tmp_path, server=server)
    return Ctx(plan=ctx.plan, root=ctx.root, prompt_dir=ctx.prompt_dir, check=ctx.check,
               adapters=ctx.adapters, lease=lease)


def test_AC1_acquire_before_ensure_model(tmp_path):
    order = []
    ctx = _ctx_with(tmp_path, FakeLease(order), OrderServer(order))
    ev = execute(Action("load_model", "", model="big"), ctx)
    assert order == ["acquire", "ensure"]
    assert ev.kind == "model_ready" and ctx.lease.acquired == ["big"]


def test_AC2_lease_timeout_is_model_failed(tmp_path, monkeypatch):
    monkeypatch.setattr(exmod, "LOAD_RETRY_WAIT", 0)
    order = []
    server = OrderServer(order)
    ctx = _ctx_with(tmp_path, FakeLease(order, fail=True), server)
    ev = execute(Action("load_model", "", model="big"), ctx)
    assert ev.kind == "model_failed" and ev.ok is False and ev.detail == "lease timeout"
    assert server.calls == []


def test_AC3_no_lease_behaves_as_before(tmp_path):
    ctx, _ = _make(tmp_path, server=FakeServer(True))
    assert ctx.lease is None
    assert execute(Action("load_model", "", model="big"), ctx).kind == "model_ready"


def test_AC4_tick_builds_and_releases_the_lease(world, monkeypatch):  # noqa: F811
    made = []

    class Spy(FakeLease):
        def __init__(self, directory, *a, **k):
            super().__init__([])
            made.append(directory)

    monkeypatch.setattr(leasemod, "Lease", Spy)
    spies = []
    orig = Spy.__init__

    def keep(self, *a, **k):
        orig(self, *a, **k)
        spies.append(self)

    monkeypatch.setattr(Spy, "__init__", keep)
    tick("demo", world["inbox"], world["root"], state_root=world["state_root"])
    assert made == [leasemod.lease_dir(world["state_root"])]
    assert spies and spies[0].released >= 1


def test_AC5_exception_still_releases(world, monkeypatch):  # noqa: F811
    spies = []

    class Spy(FakeLease):
        def __init__(self, directory, *a, **k):
            super().__init__([])
            spies.append(self)

    monkeypatch.setattr(leasemod, "Lease", Spy)

    def boom(action, ctx):
        raise RuntimeError("boom")

    monkeypatch.setattr(exmod, "execute", boom)
    with pytest.raises(RuntimeError):
        tick("demo", world["inbox"], world["root"], state_root=world["state_root"])
    assert spies and spies[0].released >= 1
