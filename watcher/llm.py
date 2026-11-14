"""llama-swap adapter: unload, load-by-probe, readiness poll.

llama-swap serves one model at a time. `ensure_model` unloads the other
models, loads the target by asking it for one token, and polls `/running`
until the target reports `ready`. Only `urllib.request` touches the network.
Every network failure gives a False or an empty list; nothing raises.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request

BASE = os.environ.get("WATCHER_LLM_URL", "http://127.0.0.1:9090")

# urllib wraps socket errors in urllib.error.URLError, a subclass of OSError.
# socket.timeout is an OSError too. json.loads raises ValueError. So these two
# catch every failure a request or a parse can produce.
_ERRORS = (OSError, ValueError)

UNLOAD_TIMEOUT = 120.0
RUNNING_TIMEOUT = 30.0
READY_STATE = "ready"


def _request(url: str, *, method: str, payload: dict | None, timeout: float) -> dict | None:
    """Send one request; return the decoded JSON body, or None on any failure."""
    body = b"" if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(url, data=body, method=method)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            if response.status != 200:
                return None
            raw = response.read()
    except _ERRORS:
        return None
    try:
        decoded = json.loads(raw)
    except _ERRORS:
        return None
    return decoded if isinstance(decoded, dict) else None


def running(base: str = BASE) -> list[tuple[str, str]]:
    """Return (model, state) for each model llama-swap reports; [] on any failure."""
    data = _request(f"{base}/running", method="GET", payload=None, timeout=RUNNING_TIMEOUT)
    if data is None:
        return []
    entries = data.get("running")
    if not isinstance(entries, list):
        return []
    pairs: list[tuple[str, str]] = []
    for entry in entries:
        if isinstance(entry, dict) and "model" in entry:
            pairs.append((entry["model"], entry.get("state", "")))
    return pairs


def unload(name: str, base: str = BASE) -> None:
    """Ask llama-swap to unload one model. Ignores every failure."""
    _request(f"{base}/api/models/unload/{name}", method="POST", payload=None,
             timeout=UNLOAD_TIMEOUT)


def probe(name: str, base: str = BASE, timeout: float = 1800) -> bool:
    """Ask for a one-token completion; True on HTTP 200 with a first choice.

    The request itself makes llama-swap load `name`, so `timeout` doubles as
    the load window.
    """
    payload = {
        "model": name,
        "max_tokens": 1,
        "messages": [{"role": "user", "content": "ok"}],
    }
    data = _request(f"{base}/v1/chat/completions", method="POST", payload=payload,
                    timeout=timeout)
    if data is None:
        return False
    choices = data.get("choices")
    return isinstance(choices, list) and len(choices) > 0


def ensure_model(
    name: str,
    base: str = BASE,
    load_timeout: float = 1800,
    poll: float = 10,
    sleep=time.sleep,
    clock=time.monotonic,
) -> bool:
    """Make `name` the ready model; True only after a ready state and a completion."""
    for model, _state in running(base):
        if model != name:
            unload(model, base)

    deadline = clock() + load_timeout
    if not probe(name, base, timeout=load_timeout):
        return False

    while (name, READY_STATE) not in running(base):
        if clock() >= deadline:
            return False
        sleep(poll)

    return probe(name, base, timeout=60)
