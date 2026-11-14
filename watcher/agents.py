"""Agents that run external CLI tools."""

import subprocess
from pathlib import Path

from watcher.omp import QUESTION, _tail
from watcher.ports import AgentResult


class CommandAgent:
    """Runs any CLI agent from an argv template.

    Fields: {role} {model} {prompt_file} {task} {worktree} {tools}.

    Example config:

        agent = "watcher.agents:CommandAgent"
        [options.agent]
        argv = ["pi", "-p", "--model", "{model}", "--tools", "{tools}", "--append-system-prompt", "{prompt_file}", "{task}"]
        edit_tools = "read,edit,write,bash"
        read_tools = "read,grep,find,write"
    """

    def __init__(self, argv: list[str], timeout: float = 1200, edit_tools: str = "", read_tools: str = "", **_):
        self.argv = list(argv)
        self.timeout = timeout
        self.edit_tools = edit_tools
        self.read_tools = read_tools

    def run(self, role: str, model: str, worktree: str, prompt_file: str, task: str) -> AgentResult:
        question = Path(worktree) / QUESTION
        question.unlink(missing_ok=True)
        tools = self.read_tools if role in ("review", "pr_review") else self.edit_tools
        fields = dict(role=role, model=model, prompt_file=prompt_file, task=task, worktree=worktree, tools=tools)
        argv = [part.format(**fields) for part in self.argv]
        try:
            proc = subprocess.run(
                argv, cwd=worktree, stdin=subprocess.DEVNULL,
                capture_output=True, text=True, timeout=self.timeout,
            )
        except subprocess.TimeoutExpired as exc:
            return AgentResult("timeout", _tail(exc.stderr, exc.stdout))
        if question.exists():
            return AgentResult("question", question.read_text())
        outcome = "done" if proc.returncode == 0 else "error"
        return AgentResult(outcome, _tail(proc.stderr, proc.stdout))
