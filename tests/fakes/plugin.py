"""Fake plug-in classes. Each records calls and stores constructor kwargs."""
from watcher.ports import AgentResult, GateResult


class _Base:
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls = []


class FakeAgent(_Base):
    def run(self, role, model, worktree, prompt_file, task, **kw):
        self.calls.append(("run", role, model, worktree, prompt_file, task))
        return AgentResult("ok", "")


class FakeGate(_Base):
    def lane_worktree(self, root, prd, repo, **kw):
        self.calls.append(("lane_worktree", root, prd, repo))
        return f"{root}/{prd}/{repo}"

    def ensure_lane(self, prd, repo, base, check, root, **kw):
        self.calls.append(("ensure_lane", prd, repo, base, check, root))
        return f"{root}/{prd}/{repo}"

    def verify(self, worktree, **kw):
        self.calls.append(("verify", worktree))
        return GateResult(True, "")

    def review(self, worktree, **kw):
        self.calls.append(("review", worktree))
        return GateResult(True, "")


class FakeServer(_Base):
    def ensure_model(self, name, **kw):
        self.calls.append(("ensure_model", name))
        return True


class FakeNotifier(_Base):
    def notify(self, title, body, **kw):
        self.calls.append(("notify", title, body))


class FakeBrokenAgent(_Base):
    """Lacks the Agent.run method."""

    def other(self):
        return None
