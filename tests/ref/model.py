"""Dict-based reference model for the flash/implement rules of ticket 04 (orchestrator-written oracle).

State dicts have the same field names as watcher.types.to_json output (tuples as lists).
ref_step(state, event) -> (new_state, actions); events and actions are plain dicts.
Tickets 05 to 09 extend this reference in their red commits.
"""
import copy

PHASE_MODEL = {"flash": "qwen3.8-flash-next", "review": "qwen3.8-27b-w8a8",
               "pr": "glm-5.3-flash-maya", "done": None}


def _status(state, key):
    for lane in state["lanes"]:
        for t in lane["tickets"]:
            if t["key"] == key:
                return t["status"]
    return ""


def ready_tickets(state, lane):
    """Pending tickets of this lane with batch <= state.batch and all deps approved, in order."""
    return [t for t in lane["tickets"]
            if t["status"] == "pending" and t["batch"] <= state["batch"]
            and all(_status(state, d) == "approved" for d in t["depends_on"])]


def _load_action(phase):
    return {"kind": "load_model", "key": "", "model": PHASE_MODEL[phase], "detail": ""}


def _has_ready(state):
    return any(ready_tickets(state, lane) for lane in state["lanes"])


def _has_changes(state):
    return any(t["status"] == "changes" for lane in state["lanes"] for t in lane["tickets"])


def _block_check(state):
    """Park pending tickets whose dependency is needs_you or skipped. Return notify actions."""
    actions = []
    for lane in state["lanes"]:
        for t in lane["tickets"]:
            if t["status"] != "pending":
                continue
            dep = next((d for d in t["depends_on"]
                        if _status(state, d) in ("needs_you", "skipped")), None)
            if dep is None:
                continue
            t["status"] = "needs_you"
            lane["busy"] = False
            state["needs_you"].append({"key": t["key"], "reason": "dependency_blocked",
                                       "detail": dep})
            actions.append({"kind": "notify", "key": t["key"], "model": "",
                            "detail": f"dependency_blocked: {t['key']}"})
    return actions


def _dispatch(state):
    actions = _block_check(state)
    if state["phase"] == "review":
        return actions + _dispatch_review(state)
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


def _find(state, key, status="running"):
    for lane in state["lanes"]:
        for t in lane["tickets"]:
            if t["key"] == key and (status is None or t["status"] == status):
                return lane, t
    return None, None


def _park(state, key, reason, detail=""):
    for lane in state["lanes"]:
        for t in lane["tickets"]:
            if t["key"] == key:
                t["status"] = "needs_you"
                lane["busy"] = False
    state["needs_you"].append({"key": key, "reason": reason, "detail": detail})
    actions = [{"kind": "notify", "key": key, "model": "", "detail": f"{reason}: {key}"}]
    actions.extend(_dispatch(state))
    return actions


def _remove_needs(state, key):
    state["needs_you"] = [n for n in state["needs_you"] if n["key"] != key]


def _release(state, key):
    lane, t = _find(state, key, "needs_you")
    if t is None:
        lane, t = _find(state, key)
    if t is not None:
        t["status"] = "changes" if t["findings"] else "pending"
        t["verify_fails"] = 0
        lane["busy"] = False
    _remove_needs(state, key)


def ref_step(state, event):
    """Apply one event to a deep copy of `state`; return (new_state, actions)."""
    s = copy.deepcopy(state)
    kind = event["kind"]
    expected = PHASE_MODEL[s["phase"]]

    if kind == "start":
        if s["model"] != expected:
            s["model"] = ""
            return s, [_load_action(s["phase"])]
        s["load_tries"] = 0
        return s, _dispatch(s)

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

    if kind in ("implemented", "fixed") and not event.get("ok", True):
        lane, ticket = _find(s, event["key"])
        if ticket is None:
            return s, []
        ticket["verify_fails"] += 1
        if ticket["verify_fails"] == 1:
            ticket["status"] = "changes" if ticket["findings"] else "pending"
            lane["busy"] = False
            actions = _dispatch(s)
            for a in actions:
                if a["key"] == event["key"]:
                    a["detail"] = event.get("detail", "")
            return s, actions
        return s, _park(s, event["key"], "verify_failed_twice")

    if kind == "question":
        return s, _park(s, event["key"], "question", event.get("detail", ""))

    if kind == "timeout":
        return s, _park(s, event["key"], "stalled")

    if kind == "bad_verdict":
        return s, _park(s, event["key"], "bad_verdict")

    if kind == "model_failed":
        s["load_tries"] += 1
        if s["load_tries"] == 1:
            return s, [_load_action(s["phase"])]
        s["needs_you"].append({"key": "model", "reason": "model_failed",
                               "detail": event.get("detail", "")})
        return s, [{"kind": "notify", "key": "model", "model": "",
                    "detail": "model_failed: model"}]

    if kind == "phase_timeout":
        running = [t["key"] for lane in s["lanes"] for t in lane["tickets"] if t["status"] == "running"]
        actions = []
        for key in running:
            actions.extend(_park(s, key, "stalled"))
        return s, actions

    if kind == "answered":
        _release(s, event["key"])
        return s, _dispatch(s)

    if kind == "retry":
        if event["key"] == "model":
            _remove_needs(s, "model")
            s["load_tries"] = 0
            return s, [_load_action(s["phase"])]
        _release(s, event["key"])
        return s, _dispatch(s)

    if kind == "skip":
        lane, ticket = _find(s, event["key"], None)
        if ticket is not None:
            ticket["status"] = "skipped"
            lane["busy"] = False
        _remove_needs(s, event["key"])
        return s, _dispatch(s)

    if kind == "abort":
        s["phase"] = "done"
        return s, [{"kind": "write_summary", "key": "", "model": "", "detail": ""}]

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
