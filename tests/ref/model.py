"""Dict-based reference model for the flash/implement rules of ticket 04 (orchestrator-written oracle).

State dicts have the same field names as watcher.types.to_json output (tuples as lists).
ref_step(state, event) -> (new_state, actions); events and actions are plain dicts.
Tickets 05 to 09 extend this reference in their red commits.
"""
import copy

PHASE_MODEL = {"flash": "qwen3.8-flash-next", "review": "qwen3.8-27b-w8a8",
               "pr": "glm-5.3-flash-maya", "done": None}


def ready_tickets(state, lane):
    """Pending tickets of this lane with batch <= state.batch, in order."""
    return [t for t in lane["tickets"] if t["status"] == "pending" and t["batch"] <= state["batch"]]


def _load_action(phase):
    return {"kind": "load_model", "key": "", "model": PHASE_MODEL[phase], "detail": ""}


def _has_ready(state):
    return any(ready_tickets(state, lane) for lane in state["lanes"])


def _has_changes(state):
    return any(t["status"] == "changes" for lane in state["lanes"] for t in lane["tickets"])


def _dispatch(state):
    actions = []
    if state["phase"] == "review":
        return _dispatch_review(state)
    if state["phase"] != "flash":
        return actions
    for lane in state["lanes"]:
        if lane["busy"]:
            continue
        fix = next((t for t in lane["tickets"] if t["status"] == "changes"), None)
        if fix is not None:
            fix["status"] = "running"
            lane["busy"] = True
            actions.append({"kind": "fix", "key": fix["key"],
                            "model": PHASE_MODEL["flash"], "detail": fix["findings"]})
            continue
        ready = ready_tickets(state, lane)
        if not ready:
            continue
        ticket = ready[0]
        ticket["status"] = "running"
        lane["busy"] = True
        actions.append({"kind": "implement", "key": ticket["key"],
                        "model": PHASE_MODEL[state["phase"]], "detail": ""})
    if not any(lane["busy"] for lane in state["lanes"]) and not _has_ready(state) \
            and not _has_changes(state):
        state["phase"] = "review"
        state["model"] = ""
        actions.append(_load_action("review"))
    return actions


def _reviewable(state):
    return any(t["status"] in ("implemented", "fixed")
               for lane in state["lanes"] for t in lane["tickets"])


def _dispatch_review(state):
    actions = []
    for lane in state["lanes"]:
        if lane["busy"]:
            continue
        ticket = next((t for t in lane["tickets"] if t["status"] in ("implemented", "fixed")), None)
        if ticket is None:
            continue
        detail = "fixed" if ticket["status"] == "fixed" else ""
        ticket["status"] = "running"
        lane["busy"] = True
        actions.append({"kind": "review", "key": ticket["key"],
                        "model": PHASE_MODEL["review"], "detail": detail})
    if not any(lane["busy"] for lane in state["lanes"]) and not _reviewable(state):
        return _next_phase(state, actions)
    return actions


def _next_phase(state, actions):
    statuses = [t["status"] for lane in state["lanes"] for t in lane["tickets"]]
    batches = [t["batch"] for lane in state["lanes"] for t in lane["tickets"]]
    more = ("changes" in statuses) or any(
        t["status"] == "pending" and t["batch"] == state["batch"] + 1
        for lane in state["lanes"] for t in lane["tickets"])
    if more:
        state["phase"] = "flash"
        if not any(t["status"] in ("pending", "running") and t["batch"] == state["batch"]
                   for lane in state["lanes"] for t in lane["tickets"]):
            state["batch"] += 1
        state["model"] = ""
        actions.append(_load_action("flash"))
    else:
        state["phase"] = "pr"
        state["model"] = ""
        actions.append(_load_action("pr"))
    return actions


def ref_step(state, event):
    """Apply one event to a deep copy of `state`; return (new_state, actions)."""
    s = copy.deepcopy(state)
    kind = event["kind"]
    expected = PHASE_MODEL[s["phase"]]

    if kind == "start":
        if s["model"] != expected:
            s["model"] = ""
            return s, [_load_action(s["phase"])]
        return s, []

    if kind == "model_ready":
        if event.get("detail") != expected:
            s["model"] = ""
            return s, [_load_action(s["phase"])]
        s["model"] = event["detail"]
        s["load_tries"] = 0
        return s, _dispatch(s)

    if kind == "reviewed":
        target = None
        for lane in s["lanes"]:
            for ticket in lane["tickets"]:
                if ticket["key"] == event["key"] and ticket["status"] == "running":
                    target = (lane, ticket)
        if target is None:
            return s, []
        lane, ticket = target
        lane["busy"] = False
        if event.get("ok", True):
            ticket["status"] = "approved"
        elif ticket["fix_rounds"] >= 1:
            ticket["status"] = "needs_you"
            s["needs_you"].append({"key": ticket["key"], "reason": "review_rejected_twice",
                                  "detail": event.get("detail", "")})
        else:
            ticket["status"] = "changes"
            ticket["findings"] = event.get("detail", "")
        return s, _dispatch(s)

    if kind == "fixed" and event.get("ok", True):
        target = None
        for lane in s["lanes"]:
            for ticket in lane["tickets"]:
                if ticket["key"] == event["key"] and ticket["status"] == "running":
                    target = (lane, ticket)
        if target is None:
            return s, []
        lane, ticket = target
        ticket["status"] = "fixed"
        ticket["sha"] = event.get("sha", "")
        ticket["fix_rounds"] += 1
        lane["busy"] = False
        return s, _dispatch(s)

    if kind == "implemented" and event.get("ok", True):
        target = None
        for lane in s["lanes"]:
            for ticket in lane["tickets"]:
                if ticket["key"] == event["key"] and ticket["status"] == "running":
                    target = (lane, ticket)
        if target is None:
            return s, []
        lane, ticket = target
        ticket["status"] = "implemented"
        ticket["sha"] = event.get("sha", "")
        lane["busy"] = False
        return s, _dispatch(s)

    return s, []
