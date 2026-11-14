"""Executor: run one Action through the adapters and report the result as an Event.

It keeps no state and never raises: an unexpected exception becomes a `timeout` Event.
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

from watcher import gitops, prompts, verdict
from watcher import lease as leasemod
from watcher.adapters import default_adapters
from watcher.inbox import Plan
from watcher.ports import Adapters
from watcher.types import Action, Event

# Tickets 20 and 21 report notify, open_pr and write_summary; this file reports none.
HANDLED_ELSEWHERE = ("notify", "open_pr", "write_summary")
# omp outcomes that stop an action before `hk verify` can mean anything.
STALLS = {"question": "question", "timeout": "timeout"}
# Editing roles, as (event kind, commit kind): each verifies, then commits.
EDIT_ROLES = {"implement": ("implemented", "ticket"), "fix": ("fixed", "fix"),
              "pr_fix": ("pr_fixed", "fix")}
# Verdict words a reviewer may write, mapped to the two words parse_verdict accepts.
WORDS = {"APPROVE": "APPROVED", "REQUEST_CHANGES": "CHANGES"}
VERDICTS_DIR = os.path.join(".agent", "verdicts")
PR_VERDICT_FILE = os.path.join(".agent", "pr-verdict.json")
REVIEW_TRIES = 2
LOAD_RETRY_WAIT = float(os.environ.get("WATCHER_LOAD_RETRY_WAIT", "60"))
LEASE_WAIT = 1800.0


@dataclass(frozen=True)
class Ctx:
    plan: Plan
    root: str
    prompt_dir: str
    check: dict[str, str]
    adapters: Adapters = field(default_factory=default_adapters)
    templates: str = ""
    lease: "leasemod.Lease | None" = None  # None: no lease, as before


def execute(action: Action, ctx: Ctx) -> Event | None:
    """Run one action; return the event that reports its result, or None."""
    if action.kind in HANDLED_ELSEWHERE:
        return None
    try:
        return _ACTIONS[action.kind](action, ctx)
    except Exception as exc:  # never raise: the loop must see an event
        return Event("timeout", key=action.key, ok=False, detail=repr(exc))


def _worktree(ctx: Ctx, key: str) -> str:
    """The lane worktree that owns this key (`<repo>/<nn>` or `<repo>`)."""
    return ctx.adapters.gate.lane_worktree(ctx.root, ctx.plan.state.prd, key.split("/", 1)[0])


def _run(action: Action, ctx: Ctx, wt: str, role: str, fail_kind: str = "",
         **inputs) -> Event | None:
    """Prompt, run omp once; return the question, timeout or error event, else None."""
    path, task = prompts.write_prompt(role, ctx.prompt_dir, key=action.key,
                                       templates=ctx.templates, **inputs)
    result = ctx.adapters.agent.run(role, action.model, wt, path, task)
    if result.outcome == "error" and fail_kind:
        return Event(fail_kind, key=action.key, ok=False, detail="omp error: " + result.detail)
    if result.outcome not in STALLS:
        return None
    return Event(STALLS[result.outcome], key=action.key, ok=False, detail=result.detail)


def _parse(path: str, sha: str) -> verdict.Verdict:
    """`verdict.parse_verdict`, mapping the APPROVE and REQUEST_CHANGES spellings."""
    try:
        data = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        data["verdict"] = WORDS.get(data.get("verdict"), data.get("verdict"))
    except (AttributeError, OSError, TypeError, ValueError):
        return verdict.parse_verdict(path, sha)  # it names its own reason
    with tempfile.NamedTemporaryFile("w", suffix=".json", delete=False) as copy:
        json.dump(data, copy)
    try:
        return verdict.parse_verdict(copy.name, sha)
    finally:
        os.unlink(copy.name)


def _load_model(action: Action, ctx: Ctx) -> Event:
    """Point llama-swap at the model; report whether it answered."""
    if ctx.lease is not None:
        try:
            ctx.lease.acquire(action.model, timeout=LEASE_WAIT)
        except leasemod.LeaseTimeout:
            return Event("model_failed", key=action.key, ok=False, detail="lease timeout")
    ready = ctx.adapters.model_server.ensure_model(action.model)
    if not ready:  # give the host time to free RAM before the core asks again
        time.sleep(LOAD_RETRY_WAIT)
    return Event("model_ready" if ready else "model_failed", key=action.key,
                 ok=ready, detail=action.model)


def _changed(wt: str) -> bool:
    """True when the worktree has any change against HEAD (.agent/ is excluded by hk)."""
    out = subprocess.run(["git", "-C", wt, "status", "--porcelain"],
                         check=True, capture_output=True, text=True).stdout
    return any(not line[3:].startswith(".agent/") for line in out.splitlines())


def _scope_contract(contract: pathlib.Path, base_sha: str, ticket_file: str) -> None:
    """Point hk at this ticket only: review diffs base_sha...HEAD against ticket_file."""
    data = json.loads(contract.read_text(encoding="utf-8"))
    data["base_ref"] = base_sha
    if ticket_file:
        data["ticket_file"] = ticket_file
    contract.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _discard_source_edits(wt: str) -> None:
    """Reviewers may write only their verdict under .agent/; drop any other change."""
    subprocess.run(["git", "-C", wt, "checkout", "--", "."], capture_output=True)
    subprocess.run(["git", "-C", wt, "clean", "-fdq", "-e", ".agent"], capture_output=True)


def _edit(action: Action, ctx: Ctx) -> Event:
    """implement, fix and pr_fix: prompt, run, verify, then commit when green."""
    kind, commit_kind = EDIT_ROLES[action.kind]
    key, wt = action.key, _worktree(ctx, action.key)
    ticket_file = ctx.plan.ticket_files.get(key, "")
    findings = "" if action.kind == "implement" else action.detail
    # The human's answer file, when it exists, lets the worker see both sides.
    answer = pathlib.Path(ctx.prompt_dir, os.pardir, "answers",
                          f"{key.replace('/', '_')}.md")
    failure = answer.read_text(encoding="utf-8") if answer.is_file() else ""
    contract = pathlib.Path(wt, ".agent", "contract.json")
    before = gitops.head(wt)
    if contract.is_file():  # scope hk to this ticket before the worker sees it
        _scope_contract(contract, before, ticket_file)
    saved = contract.read_text(encoding="utf-8") if contract.is_file() else None
    try:
        stalled = _run(action, ctx, wt, action.kind, fail_kind=kind, ticket_file=ticket_file,
                       findings=findings, failure=failure)
    finally:  # the worker never changes its own gate
        if saved is not None:
            contract.write_text(saved, encoding="utf-8")
    if stalled is not None:
        return stalled
    if not _changed(wt):
        return Event(kind, key=key, ok=False, detail="noop: the worker changed no files")
    checked = ctx.adapters.gate.verify(wt)
    if not checked.ok:
        return Event(kind, key=key, ok=False, detail=checked.tail)
    reviewed = ctx.adapters.gate.review(wt)
    if not reviewed.ok:
        return Event(kind, key=key, ok=False, detail="hk review rejected: " + reviewed.tail)
    title = os.path.splitext(os.path.basename(ticket_file))[0] or key
    with gitops.worktree_lock(wt):
        sha = gitops.commit_ticket(wt, key, title, commit_kind)
    return Event(kind, key=key, ok=True, sha=sha)


def _review(action: Action, ctx: Ctx) -> Event:
    """Review one commit; a malformed verdict earns the reviewer one more run."""
    key, sha = action.key, action.detail
    wt = _worktree(ctx, key)
    ticket_file = ctx.plan.ticket_files.get(key, "")
    target = os.path.join(wt, VERDICTS_DIR, f"{key.rsplit('/', 1)[-1]}.json")
    reason = ""
    for _attempt in range(REVIEW_TRIES):
        stalled = _run(action, ctx, wt, "review", ticket_file=ticket_file, commit=sha)
        _discard_source_edits(wt)
        if stalled is not None:
            return stalled
        try:
            parsed = _parse(target, sha)
        except verdict.BadVerdict as exc:
            reason = str(exc)
            continue
        return Event("reviewed", key=key, ok=parsed.approved,
                     detail=parsed.findings_json)
    return Event("bad_verdict", key=key, ok=False, detail=reason)


def _pr_review(action: Action, ctx: Ctx) -> Event:
    """Review the whole lane: spec, diff, every verdict file, then the pr verdict."""
    key = action.key
    wt = _worktree(ctx, key)
    diff = subprocess.run(["git", "-C", wt, "diff", f"{ctx.plan.base}...HEAD"],
                          capture_output=True, text=True, check=True).stdout
    files = sorted(pathlib.Path(wt, VERDICTS_DIR).glob("*.json"))
    stalled = _run(action, ctx, wt, "pr_review", diff=diff,
                   spec_file=ctx.plan.specs.get(key.split("/", 1)[0], ""),
                   verdicts="\n".join(p.read_text(encoding="utf-8") for p in files))
    _discard_source_edits(wt)
    if stalled is not None:
        return stalled
    parsed = _parse(os.path.join(wt, PR_VERDICT_FILE), gitops.head(wt))
    return Event("pr_reviewed", key=key, ok=parsed.approved,
                 detail=parsed.findings_json)


_ACTIONS = {"load_model": _load_model, "implement": _edit, "fix": _edit,
            "pr_fix": _edit, "review": _review, "pr_review": _pr_review}
