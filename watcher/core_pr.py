"""Decide what a PR review or PR fix result does to a repo lane."""
from __future__ import annotations

from dataclasses import replace

from watcher import core as _core
from .types import Action, Event, Lane, NeedsYou, State

def _pr_reviewed(
    state: State, event: Event
) -> tuple[State, tuple[Action, ...]]:
    """Record a PR verdict: open the PR, spend the one retry, or park the repo."""
    found = _core._lane_by_repo(state, event.key)
    if found is None or found[1].pr_status != "running":
        return state, ()
    i, lane = found
    lane = replace(lane, busy=False)

    if event.ok:
        state = _core._set_lane(state, i, replace(lane, pr_status="approved"))
        actions: tuple[Action, ...] = (Action("open_pr", key=lane.repo),)
    elif lane.pr_tries == 0:
        # The first objection keeps the lane free and emits nothing: the flash
        # phase end is what routes this repo to pr_fix.
        state = _core._set_lane(state, i, replace(
            lane, pr_tries=1, pr_status=_core.OBJECTION_PREFIX + event.detail))
        actions = ()
    else:
        state = _parked_repo(state, i, lane, event.detail)
        actions = (_notify_repo(lane.repo, event.detail),)
    return _core._pr_phase_end(state, actions)


def _pr_fixed(state: State, event: Event) -> tuple[State, tuple[Action, ...]]:
    """Record a pr_fix result: clear the objection, or treat a failure as a second one."""
    found = _core._lane_by_repo(state, event.key)
    if found is None or found[1].pr_status != "fixing":
        return state, ()
    i, lane = found
    lane = replace(lane, busy=False)

    if not event.ok:
        state = _parked_repo(state, i, lane, event.detail)
        return state, (_notify_repo(lane.repo, event.detail),)
    return _core._dispatch(_core._set_lane(state, i, replace(lane, pr_status="none")))


def _parked_repo(state: State, i: int, lane: Lane, detail: str) -> State:
    """This lane goes to Needs you with reason `pr_objected_twice`."""
    state = _core._set_lane(state, i, replace(lane, pr_status="needs_you"))
    return replace(state, needs_you=state.needs_you + (
        NeedsYou(lane.repo, "pr_objected_twice", detail),))


def _notify_repo(repo: str, detail: str) -> Action:
    """Tell the human this repo got its second PR objection."""
    return Action("notify", key=repo, detail=f"pr_objected_twice: {repo}")


def _dispatch_pr(
    state: State, actions: tuple[Action, ...]
) -> tuple[State, tuple[Action, ...]]:
    """Give one PR review to every idle, finished lane whose pr_status is still none."""
    lanes: list[Lane] = []
    pr_actions = list(actions)

    for lane in state.lanes:
        if lane.busy or lane.pr_status != "none" or not _core.finished(lane):
            lanes.append(lane)
            continue
        pr_actions.append(Action("pr_review", key=lane.repo, model=_core.model_for(state, "pr")))
        lanes.append(replace(lane, busy=True, pr_status="running"))

    state = replace(state, lanes=tuple(lanes))
    if len(pr_actions) > len(actions) or any(lane.busy for lane in state.lanes):
        return state, tuple(pr_actions)
    # Nothing to review: released tickets send the run back, else close the round.
    if _open_ticket_work(state):
        return _back_to_work(state, tuple(pr_actions))
    objected = any(lane.pr_status.startswith(_core.OBJECTION_PREFIX) for lane in state.lanes)
    parked = any(t.status == "needs_you" for lane in state.lanes for t in lane.tickets)
    if objected or not parked:
        return _pr_phase_end(state, tuple(pr_actions))
    return state, tuple(pr_actions)  # only parked work left: wait for the user


def _open_ticket_work(state: State) -> bool:
    """Work the run can do now: ready pending tickets, or changes/implemented/fixed ones."""
    return any(
        _core.ready_tickets(state, lane)
        or any(t.status in ("changes", "implemented", "fixed") for t in lane.tickets)
        for lane in state.lanes)


def _back_to_work(state: State, actions: tuple[Action, ...]) -> tuple[State, tuple[Action, ...]]:
    """A ticket released in the pr phase goes back through review or flash."""
    if any(t.status in ("implemented", "fixed") for lane in state.lanes for t in lane.tickets):
        return replace(state, phase="review", model=""), actions + (
            Action("load_model", model=_core.model_for(state, "review")),)
    return replace(state, phase="flash", model=""), actions + (
        Action("load_model", model=_core.model_for(state, "flash")),)


def _pr_phase_end(
    state: State, actions: tuple[Action, ...]
) -> tuple[State, tuple[Action, ...]]:
    """Close the pr round once no lane is busy: objections go to flash, else done."""
    if state.phase != "pr" or any(lane.busy for lane in state.lanes):
        return state, actions
    if any(_core.finished(lane) and lane.pr_status == "none" for lane in state.lanes):
        return state, actions
    if any(lane.pr_status.startswith(_core.OBJECTION_PREFIX) for lane in state.lanes):
        return replace(state, phase="flash", model=""), actions + (
            Action("load_model", model=_core.model_for(state, "flash")),
        )
    return replace(state, phase="done"), actions + (Action("write_summary"),)
