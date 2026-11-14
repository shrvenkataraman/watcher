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
