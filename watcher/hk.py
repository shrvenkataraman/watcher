"""hk adapter: one worktree per lane, plus `hk verify` results."""

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass

HK = os.environ.get("WATCHER_HK", "hk")


def lane_worktree(root: str, prd: str, repo: str) -> str:
    """Path of the hk worktree for one lane."""
    return f"{root}/features/{prd}/{repo}"


def _tail(text: str, limit: int = 2000) -> str:
    text = (text or "").strip()
    return text[-limit:]


def ensure_lane(prd: str, repo: str, base: str, check: str, root: str) -> str:
    """Create the hk worktree for this lane; return its path."""
    wt = lane_worktree(root, prd, repo)
    if os.path.exists(os.path.join(wt, ".agent", "contract.json")):
        return wt

    cmd = [HK, "new", "--task", prd, "--repo", repo, "--base", base, "--check", check]
    proc = subprocess.run(cmd, cwd=root, capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(_tail(proc.stderr))
    return wt


@dataclass(frozen=True)
class VerifyResult:
    green: bool
    tail: str


def _joined_output_tail(checks: list) -> str:
    """output_tail of every check whose exit_code is not 0, joined."""
    parts: list[str] = []
    for c in checks:
        if not isinstance(c, dict) or c.get("exit_code", 0) == 0:
            continue
        tail = c.get("output_tail", "")
        if isinstance(tail, (list, tuple)):
            tail = "\n".join(str(line) for line in tail)
        parts.append(str(tail))
    return "\n".join(parts)


def verify(worktree: str, timeout: float = 1200) -> VerifyResult:
    """Run `hk verify` in the worktree and read its receipt."""
    proc = subprocess.run(
        [HK, "verify"], cwd=worktree, capture_output=True, text=True, timeout=timeout
    )

    receipt_path = os.path.join(worktree, ".agent", "receipt.json")
    if not os.path.exists(receipt_path):
        return VerifyResult(green=False, tail=_tail(proc.stderr))

    with open(receipt_path, encoding="utf-8") as f:
        receipt = json.load(f)

    if not receipt.get("scope_ok", True):
        files = receipt.get("files_changed", 0)
        lines = receipt.get("lines_changed", 0)
        return VerifyResult(green=False, tail=f"scope: {files} files, {lines} lines")

    green = receipt.get("verdict") == "green"
    if green:
        return VerifyResult(green=True, tail="")
    return VerifyResult(green=False, tail=_joined_output_tail(receipt.get("checks", [])))
