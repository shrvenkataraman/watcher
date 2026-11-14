"""Run loop (ticket 22): a tick steps the pipeline under <state_dir>/run.lock."""

from __future__ import annotations

import fcntl
from dataclasses import replace
import json
import os
import subprocess
import sys
import time
from collections import deque
from datetime import datetime
from itertools import count

from watcher.config import Config, load_config
from watcher.plugins import build_adapters
from watcher import core, executor, gh, gitops, hk, report, resume, store
from watcher import inbox as inboxmod
from watcher import lease as leasemod
from watcher.types import PHASE_MODEL, Action, Event, State, event_from_json

RECONCILED: set[str] = set()  # state directories whose git history this process read
STARTED: set[str] = set()  # state directories this process already sent `start` for

PHASE_ROLE = {"flash": "working", "review": "review", "pr": "pr"}


def queue_counts(state: State) -> dict[str, int]:
    """Count the tickets this project still has work for, per lease role."""
    statuses = {t.key: t.status for lane in state.lanes for t in lane.tickets}
    working = sum(
        1 for lane in state.lanes for t in lane.tickets
        if t.status in ("pending", "changes")
        and not any(statuses.get(d) in ("needs_you", "skipped") for d in t.depends_on)
    )
    review = sum(1 for lane in state.lanes for t in lane.tickets
                 if t.status == "implemented")
    pr = sum(1 for lane in state.lanes
             if all(t.status in ("approved", "skipped") for t in lane.tickets)
             and lane.pr_status != "approved")
    return {"working": working, "review": review, "pr": pr}


def _check(manifest: dict, repo: str) -> str:
    """The check command for a repo: its manifest entry first, then the manifest top."""
    entry = manifest.get("repos", {}).get(repo)
    parts = (entry, manifest) if isinstance(entry, dict) else (manifest,)
    return next((p["check"] for p in parts if isinstance(p.get("check"), str)), "")


def _ticket_check(plan, repo: str) -> str:
    """The first `Check:` line in the repo's ticket files, or ''."""
    for key in sorted(plan.ticket_files):
        if key.split("/", 1)[0] != repo:
            continue
        try:
            with open(plan.ticket_files[key], encoding="utf-8") as handle:
                for line in handle:
                    if line.startswith("Check:"):
                        return line.split(":", 1)[1].strip()
        except OSError:
            pass
    return ""


def _committed(plan, root: str, adapters) -> dict[str, dict[str, str]]:
    """Ticket commits per repo, read from the whole history, not only past `base`."""
    found = {}
    for lane in plan.state.lanes:
        if os.path.isdir(wt := adapters.gate.lane_worktree(root, plan.state.prd, lane.repo)):
            roots = subprocess.run(["git", "-C", wt, "rev-list", "--max-parents=0", "HEAD"],
                                   check=True, capture_output=True, text=True).stdout.split()
            found[lane.repo] = gitops.committed_keys(wt, roots[-1] if roots else "HEAD")
    return found


def _drain_queue(prd: str, state_root: str | None) -> list[Event]:
    """Rename queue.jsonl to queue.jsonl.<n>, then return the events it holds."""
    path = os.path.join(store.state_dir(prd, state_root), "queue.jsonl")
    if not os.path.isfile(path):
        return []
    n = next(i for i in count(1) if not os.path.exists(f"{path}.{i}"))
    os.rename(path, moved := f"{path}.{n}")
    with open(moved, encoding="utf-8") as handle:
        lines = handle.read().splitlines()
    events: list[Event] = []
    for index, line in enumerate(lines):
        try:
            events.append(event_from_json(json.loads(line)))
        except (ValueError, TypeError):
            if line.strip() and index != len(lines) - 1:
                raise  # blank lines and a torn last line stay out of this tick
    return events


def _act(action: Action, state: State, plan, ctx: executor.Ctx, prd: str,
         state_root: str | None, now) -> Event | None:
    """Run one action; return the Event that reports its result, or None."""
    adapters = getattr(ctx, "adapters", None)  # bare test contexts carry none
    notify = adapters.notifier.notify if adapters else report.notify
    lane_wt = adapters.gate.lane_worktree if adapters else hk.lane_worktree
    if action.kind == "notify":
        notify(action.key, action.detail)
    elif action.kind == "write_summary":
        report.write_summary(state, store.read_events(prd, state_root),
                             os.path.join(store.state_dir(prd, state_root), "summary.md"), now())
    elif action.kind == "open_pr":
        body = os.path.join(store.state_dir(prd, state_root), "pr-body.md")
        with open(body, "w", encoding="utf-8") as handle:
            handle.write(f"# {plan.state.prd}: {action.key}\n\n"
                         f"Spec: {plan.specs.get(action.key, '')}\n")
        try:  # a refused or failed PR must not crash the run; tell the user instead
            gh.open_pr(lane_wt(ctx.root, plan.state.prd, action.key), plan.base,
                       f"{plan.state.prd}: {action.key}", body)
        except Exception as exc:
            notify(action.key, f"open_pr failed, open it by hand: {exc}")
    else:
        if action.kind == "review":  # the reviewer checks the ticket's own commit
            action = replace(action, detail=_ticket_sha(state, action.key))
        return executor.execute(action, ctx)
    return None


def _ticket_sha(state: State, key: str) -> str:
    """The commit recorded for a ticket key, or "" when it has none."""
    return next((t.sha for lane in state.lanes for t in lane.tickets if t.key == key), "")


def tick(prd: str, inbox: str, root: str, state_root: str | None = None,
         now=lambda: datetime.now().isoformat(timespec="seconds"),
         cfg: Config | None = None) -> bool:
    """Advance the pipeline one round from saved state; False when the run is done."""
    os.makedirs(directory := store.state_dir(prd, state_root), exist_ok=True)
    with open(os.path.join(directory, "run.lock"), "a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return True
        cfg = cfg or load_config()
        adapters = build_adapters(cfg)
        lease_directory = leasemod.lease_dir(state_root)
        lease = leasemod.Lease(lease_directory)
        plan = inboxmod.load_inbox(inbox)
        with open(os.path.join(inbox, inboxmod.MANIFEST_FILE), encoding="utf-8") as handle:
            manifest = json.load(handle)
        checks = {lane.repo: _check(manifest, lane.repo) or _ticket_check(plan, lane.repo) for lane in plan.state.lanes}
        saved = store.load(prd, state_root)
        if saved is None:
            for lane in plan.state.lanes:
                adapters.gate.ensure_lane(prd, lane.repo, plan.base, checks[lane.repo], root)
            models = tuple(sorted(cfg.models.items()))
            default = {k: v for k, v in PHASE_MODEL.items() if k != "done"}
            state = plan.state if dict(models) == default else replace(plan.state, models=models)
        elif directory not in RECONCILED:  # one git-history read per process
            RECONCILED.add(directory)
            state = resume.reconcile(saved, _committed(plan, root, adapters))
        else:
            state = saved
        ctx = executor.Ctx(plan=plan, root=root, check=checks,
                           prompt_dir=os.path.join(directory, "prompts"), adapters=adapters,
                           templates=cfg.prompt_dir, lease=lease)
        # One `start` per process, and again only after something else happened,
        # so an idle run waiting on the user does not grow the event log.
        events = store.read_events(prd, state_root)
        first = directory not in STARTED or not events or events[-1].kind != "start"
        STARTED.add(directory)
        pending = deque([*([Event("start")] if first else []), *_drain_queue(prd, state_root)])
        try:
            while pending:
                store.append_event(prd, event := pending.popleft(), state_root)
                state, actions = core.step(state, event)
                store.save(state, state_root)
                leasemod.publish(lease_directory, prd, queue_counts(state))
                lease.role = PHASE_ROLE.get(state.phase)
                if state.phase == "done":
                    leasemod.clear(lease_directory, prd)
                for action in actions:
                    if (ev := _act(action, state, plan, ctx, prd, state_root, now)) is not None:
                        pending.append(ev)
        finally:
            if state.phase == "done":  # a finished project holds no queue
                leasemod.clear(lease_directory, prd)
            lease.release()
        if state.phase == "done":
            report.write_summary(state, store.read_events(prd, state_root),
                                 os.path.join(directory, "summary.md"), now())
    return state.phase != "done"


def run(prd: str, inbox: str, root: str, state_root: str | None = None,
        idle: float = 5, sleep=time.sleep, cfg: Config | None = None) -> int:
    """Tick until the run is done; return 0, or 3 when another run holds this prd."""
    # The process lock sits beside the state folder, so deleting that folder
    # never lets a second `watcher run` start for the same prd.
    parent = os.path.dirname(store.state_dir(prd, state_root))
    os.makedirs(parent, exist_ok=True)
    with open(os.path.join(parent, f"{prd}.run.lock"), "a", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"watcher: another run holds {prd}", file=sys.stderr)
            return 3
        while tick(prd, inbox, root, state_root=state_root, cfg=cfg):
            sleep(idle)
    return 0
