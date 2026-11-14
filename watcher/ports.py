from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class AgentResult:
    outcome: str
    detail: str


@dataclass(frozen=True)
class GateResult:
    ok: bool
    tail: str


@runtime_checkable
class Agent(Protocol):
    """Runs one agent role in a worktree and reports its outcome."""

    def run(self, role: str, model: str, worktree: str, prompt_file: str, task: str) -> AgentResult: ...


@runtime_checkable
class Gate(Protocol):
    """Provides lane worktrees and the verify and review checks."""

    def lane_worktree(self, root: str, prd: str, repo: str) -> str: ...
    def ensure_lane(self, prd: str, repo: str, base: str, check: str, root: str) -> str: ...
    def verify(self, worktree: str) -> GateResult: ...
    def review(self, worktree: str) -> GateResult: ...


@runtime_checkable
class ModelServer(Protocol):
    """Makes a named model ready to serve and says whether it is."""

    def ensure_model(self, name: str) -> bool: ...


@runtime_checkable
class Notifier(Protocol):
    """Delivers a message to a human."""

    def notify(self, title: str, body: str) -> None: ...


@dataclass(frozen=True)
class Adapters:
    agent: Agent
    gate: Gate
    model_server: ModelServer
    notifier: Notifier
