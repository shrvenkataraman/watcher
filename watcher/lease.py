"""Model leases that let several runs share one model.

One holder takes `LOCK_SH` on `model-<name>.lock`, so several holders keep the
same model together. A run that wants another model takes `LOCK_EX` on every
other model file while it holds `switch.lock`. That exclusive probe fails while
any holder stays, so the run waits and retries. The kernel drops flocks when a
process dies, so a crash never leaves a lease stuck held.

Projects publish their queue counts under `wants/`. A role that asks for a model
is allowed only when it is the first role in `ROLES` with work, or when it equals
the role recorded in `current.json` while that queue still has work.
"""

from __future__ import annotations

import fcntl
import json
import os
import tempfile
import time
from collections.abc import Callable

from watcher import store

SWITCH_FILE = "switch.lock"
MODEL_PREFIX = "model-"
MODEL_SUFFIX = ".lock"

ROLES = ("working", "review", "pr")  # priority order, first is highest
WANTS_DIR = "wants"  # <lease dir>/wants/<project>.json
CURRENT_FILE = "current.json"  # {"role": "<role>"}, written on each acquire


class LeaseTimeout(Exception):
    """Raised when another model stays held until the deadline passes."""


def lease_dir(root: str | None = None) -> str:
    """Return <root or store._default_root()>/watcher-leases."""
    base = root if root is not None else store._default_root()
    return os.path.join(base, "watcher-leases")


def model_file(model: str) -> str:
    """Return the lock file name for a model: '/' becomes '_'."""
    return f"{MODEL_PREFIX}{model.replace('/', '_')}{MODEL_SUFFIX}"


def wants_file(directory: str, project: str) -> str:
    """Return <directory>/wants/<project>.json."""
    return os.path.join(directory, WANTS_DIR, f"{project}.json")


def publish(directory: str, project: str, counts: dict[str, int]) -> None:
    """Write one project's queue counts, with a missing role counted as 0."""
    payload = {name: int(counts.get(name, 0)) for name in ROLES}
    _write_json(wants_file(directory, project), payload)


def clear(directory: str, project: str) -> None:
    """Delete one project's wants file; a missing file is not an error."""
    try:
        os.remove(wants_file(directory, project))
    except FileNotFoundError:
        pass


def totals(directory: str) -> dict[str, int]:
    """Sum every wants file per role; an unreadable file counts as 0."""
    total = {name: 0 for name in ROLES}
    base = os.path.join(directory, WANTS_DIR)
    try:
        names = sorted(os.listdir(base))
    except OSError:
        return total
    for name in names:
        if not name.endswith(".json"):
            continue
        data = _read_json(os.path.join(base, name))
        if data is None:
            continue
        for role in ROLES:
            value = data.get(role, 0)
            if isinstance(value, bool) or not isinstance(value, int):
                continue
            total[role] += value
    return total


def _read_json(path: str) -> dict[str, object] | None:
    """Return the JSON object at `path`, or None when it is missing or unreadable."""
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: str, payload: dict[str, object]) -> None:
    """Write `payload` to `path` atomically, through a temp file in the same folder."""
    parent = os.path.dirname(path)
    os.makedirs(parent, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=parent, prefix=".tmp-", suffix=".lease")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Lease:
    """A shareable hold on one model, released by this object, by collection or by a crash."""

    def __init__(
        self,
        directory: str,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll: float = 1.0,
    ) -> None:
        self.directory = directory
        self.poll = poll
        self.role: str | None = None
        self._sleep = sleep
        self._clock = clock
        self._fd: int | None = None
        self._model: str | None = None
        self._ensure_dir()

    def __del__(self) -> None:
        """Drop the hold when nothing references this object any more.

        A run that keeps a lease keeps the object, so the hold lasts as long as
        the run. Any error here is unreportable from `__del__`, so it passes.
        """
        try:
            self.release()
        except Exception:
            pass

    def held(self) -> str | None:
        """Return the model this object holds, or None when it holds nothing."""
        return self._model

    def acquire(
        self, model: str, timeout: float = 1800, role: str | None = None
    ) -> None:
        """Hold `model`, sharing it with other holders of the same model.

        Waits until every other model is free. Raises LeaseTimeout when the
        wait passes `timeout` seconds. With a role, also waits until the queue
        order in `ROLES` grants that role; `role or self.role` is the role used,
        and no role at all keeps the old behaviour.
        """
        if self._fd is not None and self._model == model:
            return
        if self._fd is not None:
            self.release()

        want_role = role or self.role
        self._ensure_dir()
        own = model_file(model)
        deadline = self._clock() + timeout

        while True:
            switch_fd = os.open(self._path(SWITCH_FILE), os.O_RDWR | os.O_CREAT)
            try:
                try:
                    fcntl.flock(switch_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    # Another run is switching models, so wait and retry.
                    os.close(switch_fd)
                    self._wait(deadline, model)
                    continue
                free = not self._other_model_busy(own)
                if free and self._role_allowed(want_role):
                    fd = os.open(self._path(own), os.O_RDWR | os.O_CREAT)
                    fcntl.flock(fd, fcntl.LOCK_SH)
                    self._fd = fd
                    self._model = model
                    self._write_current(want_role)
            finally:
                os.close(switch_fd)
            if self._model == model and self._fd is not None:
                return
            self._wait(deadline, model)

    def release(self) -> None:
        """Drop the hold. Safe to call twice, and safe to call when nothing is held."""
        fd = self._fd
        self._fd = None
        self._model = None
        if fd is None:
            return
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    def _role_allowed(self, role: str | None) -> bool:
        """Return True when the queue order grants `role` the model now."""
        if role is None:
            return True
        counts = totals(self.directory)
        cur = self._read_current()
        if cur is not None and counts.get(cur, 0) > 0:
            return role == cur
        want = next((name for name in ROLES if counts.get(name, 0) > 0), None)
        return want is None or role == want

    def _read_current(self) -> str | None:
        """Return the role in current.json, or None when the file is missing or unreadable."""
        data = _read_json(self._path(CURRENT_FILE))
        role = data.get("role") if data is not None else None
        return role if isinstance(role, str) else None

    def _write_current(self, role: str | None) -> None:
        """Record `role` as the loaded role; keep the file untouched without a role."""
        if role is None:
            return
        _write_json(self._path(CURRENT_FILE), {"role": role})

    def _wait(self, deadline: float, model: str) -> None:
        """Stop waiting past the deadline, otherwise sleep for one poll step."""
        if self._clock() >= deadline:
            raise LeaseTimeout(model)
        self._sleep(self.poll)

    def _other_model_busy(self, own: str) -> bool:
        """Return True when some other model file is held by anyone."""
        for name in sorted(os.listdir(self.directory)):
            if not (name.startswith(MODEL_PREFIX) and name.endswith(MODEL_SUFFIX)):
                continue
            if name == own:
                continue
            fd = os.open(self._path(name), os.O_RDWR | os.O_CREAT)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                os.close(fd)
                return True
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)
        return False

    def _path(self, name: str) -> str:
        return os.path.join(self.directory, name)

    def _ensure_dir(self) -> None:
        os.makedirs(self.directory, exist_ok=True)
