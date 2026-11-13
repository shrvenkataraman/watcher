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


def _dispatch(state):
    actions = []
    if state["phase"] != "flash":
        return actions
    for lane in state["lanes"]:
        if lane["busy"]:
            continue
        ready = ready_tickets(state, lane)
        if not ready:
            continue
        ticket = ready[0]
        ticket["status"] = "running"
        lane["busy"] = True
        actions.append({"kind": "implement", "key": ticket["key"],
                        "model": PHASE_MODEL[state["phase"]], "detail": ""})
    if not any(lane["busy"] for lane in state["lanes"]) and not _has_ready(state):
        state["phase"] = "review"
        state["model"] = ""
        actions.append(_load_action("review"))
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
