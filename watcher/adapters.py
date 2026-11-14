from watcher import hk, llm, omp, report
from watcher.ports import Adapters, AgentResult, GateResult


class OmpAgent:
    def __init__(self, **options):
        self.options = options

    def run(self, role, model, worktree, prompt_file, task) -> AgentResult:
        r = omp.run_omp(role, model, worktree, prompt_file, task)
        return AgentResult(r.outcome, r.detail)


class HkGate:
    def __init__(self, **options):
        self.options = options

    def lane_worktree(self, root, prd, repo):
        return hk.lane_worktree(root, prd, repo)

    def ensure_lane(self, prd, repo, base, check, root):
        return hk.ensure_lane(prd, repo, base, check, root)

    def verify(self, worktree):
        r = hk.verify(worktree)
        return GateResult(r.green, r.tail)

    def review(self, worktree):
        r = hk.review(worktree)
        return GateResult(r.approved, r.tail)


class LlamaSwapServer:
    def __init__(self, url: str = llm.BASE, **options):
        self.url = url
        self.options = options

    def ensure_model(self, name):
        return llm.ensure_model(name, base=self.url)


class DesktopNotifier:
    def __init__(self, **options):
        self.options = options

    def notify(self, title, body):
        report.notify(title, body)


def default_adapters() -> Adapters:
    return Adapters(OmpAgent(), HkGate(), LlamaSwapServer(), DesktopNotifier())
