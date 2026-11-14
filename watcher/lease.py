"""Model leases that let several runs share one model.

One holder takes `LOCK_SH` on `model-<name>.lock`, so several holders keep the
same model together. A run that wants another model takes `LOCK_EX` on every
other model file while it holds `switch.lock`. That exclusive probe fails while
any holder stays, so the run waits and retries. The kernel drops flocks when a
process dies, so a crash never leaves a lease stuck held.
"""

from __future__ import annotations

import fcntl
import os
import time
from collections.abc import Callable

from watcher import store

SWITCH_FILE = "switch.lock"
MODEL_PREFIX = "model-"
MODEL_SUFFIX = ".lock"


class LeaseTimeout(Exception):
    """Raised when another model stays held until the deadline passes."""


def lease_dir(root: str | None = None) -> str:
    """Return <root or store._default_root()>/watcher-leases."""
    base = root if root is not None else store._default_root()
    return os.path.join(base, "watcher-leases")


def model_file(model: str) -> str:
    """Return the lock file name for a model: '/' becomes '_'."""
    return f"{MODEL_PREFIX}{model.replace('/', '_')}{MODEL_SUFFIX}"


class Lease:
    """A shareable hold on one model, released by this object or by a crash."""

    def __init__(
        self,
        directory: str,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        poll: float = 1.0,
    ) -> None:
        self.directory = directory
        self.poll = poll
        self._sleep = sleep
        self._clock = clock
        self._fd: int | None = None
        self._model: str | None = None
        self._ensure_dir()

    def held(self) -> str | None:
        """Return the model this object holds, or None when it holds nothing."""
        return self._model

    def acquire(self, model: str, timeout: float = 1800) -> None:
        """Hold `model`, sharing it with other holders of the same model.

        Waits until every other model is free. Raises LeaseTimeout when the
        wait passes `timeout` seconds.
        """
        if self._fd is not None and self._model == model:
            return
        if self._fd is not None:
            self.release()

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
                if free:
                    fd = os.open(self._path(own), os.O_RDWR | os.O_CREAT)
                    fcntl.flock(fd, fcntl.LOCK_SH)
                    self._fd = fd
                    self._model = model
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
