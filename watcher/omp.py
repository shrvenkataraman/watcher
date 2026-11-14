"""One headless omp session: argv building, the run, and the outcome."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

TOOLS = {
    "implement": "read,edit,write,bash,grep,find,ls",
    "fix": "read,edit,write,bash,grep,find,ls",
    "review": "read,grep,find,ls",
    "pr_review": "read,grep,find,ls",
    "pr_fix": "read,edit,write,bash,grep,find,ls",
}
THINKING = {
    "implement": "low",
    "fix": "low",
    "pr_fix": "low",
    "review": "medium",
    "pr_review": "medium",
}

QUESTION = Path(".agent") / "question.md"
BAD_STOP_REASONS = ("error", "aborted")
DETAIL_LINES = 40


@dataclass(frozen=True)
class OmpResult:
    outcome: str  # "done" | "question" | "timeout" | "error"
    detail: str  # question text, or last 40 lines of stderr/stdout


def build_argv(role: str, model: str, prompt_file: str, task: str) -> list[str]:
    return [
        os.environ.get("WATCHER_OMP", "omp"),
        "-p",
        "--no-session",
        "--mode",
        "json",
        "--provider",
        "llamaswap",
        "--model",
        model,
        "--thinking",
        THINKING[role],
        "--tools",
        TOOLS[role],
        f"@{prompt_file}",
        task,
    ]


def _tail(*chunks: str | None) -> str:
    lines: list[str] = []
    for chunk in chunks:
        if chunk:
            lines.extend(chunk.splitlines())
    return "\n".join(lines[-DETAIL_LINES:])


def _stop_reason_failed(stdout: str) -> bool:
    for line in stdout.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            payload = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict) and payload.get("stopReason") in BAD_STOP_REASONS:
            return True
    return False


def run_omp(
    role: str,
    model: str,
    worktree: str,
    prompt_file: str,
    task: str,
    timeout: float = 1200,
) -> OmpResult:
    question = Path(worktree) / QUESTION
    question.unlink(missing_ok=True)
    argv = build_argv(role, model, prompt_file, task)
    try:
        proc = subprocess.run(
            argv,
            cwd=worktree,
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired as exc:
        return OmpResult("timeout", _tail(exc.stderr, exc.stdout))

    if question.exists():
        return OmpResult("question", question.read_text())

    if _stop_reason_failed(proc.stdout):
        return OmpResult("error", _tail(proc.stderr, proc.stdout))

    if proc.returncode == 0:
        return OmpResult("done", _tail(proc.stderr, proc.stdout))

    return OmpResult("error", _tail(proc.stderr, proc.stdout))
