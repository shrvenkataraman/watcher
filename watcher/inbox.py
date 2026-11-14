"""Load an inbox directory into an initial State."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass

from watcher.types import Lane, State, TicketState

MANIFEST_FILE = "manifest.json"
TICKETS_DIR = "tickets"
DEFAULT_BATCH_SIZE = 5
TICKET_FILE = re.compile(r"^(\d+)-.*\.md$")


class InboxError(ValueError):
    """Raised when an inbox does not match the manifest contract."""


@dataclass(frozen=True)
class Plan:
    state: State
    base: str
    batch_size: int
    specs: dict[str, str]
    ticket_files: dict[str, str]


def _key(repo: str, nn: str | int) -> str:
    return f"{repo}/{int(nn):02d}"


def _read_manifest(root: str) -> dict:
    path = os.path.join(root, MANIFEST_FILE)
    if not os.path.isfile(path):
        raise InboxError(f"manifest.json is missing: {path}")
    try:
        with open(path, encoding="utf-8") as handle:
            data = json.load(handle)
    except ValueError:
        raise InboxError(f"manifest.json is not valid JSON: {path}") from None
    if not isinstance(data, dict) or not isinstance(data.get("repos"), dict):
        raise InboxError(f"manifest.json has no repos object: {path}")
    return data


def _entry(manifest: dict, repo: str) -> dict:
    entry = manifest["repos"][repo]
    if not isinstance(entry, dict):
        raise InboxError(f"repo {repo} has no manifest entry object")
    return entry


def _scan_tickets(root: str, repo: str) -> list[tuple[str, str]]:
    directory = os.path.join(root, TICKETS_DIR, repo)
    names = os.listdir(directory) if os.path.isdir(directory) else []
    found = sorted(
        (int(m.group(1)), _key(repo, m.group(1)), os.path.join(directory, name))
        for name in names
        if (m := TICKET_FILE.match(name))
    )
    if not found:
        raise InboxError(f"repo {repo} has no ticket files under {directory}")
    return [(key, path) for _, key, path in found]


def _edges(manifest: dict, batch_of: dict[str, int]) -> dict[str, list[str]]:
    edges: dict[str, list[str]] = {}
    for repo in sorted(manifest["repos"]):
        for nn, targets in (_entry(manifest, repo).get("depends_on") or {}).items():
            key = _key(repo, nn)
            if key not in batch_of:
                raise InboxError(f"depends_on key names no ticket: {key}")
            missing = [t for t in targets if t not in batch_of]
            if missing:
                raise InboxError(f"depends_on target names no ticket: {missing[0]}")
            edges.setdefault(key, []).extend(targets)
    _check_cycle(edges)
    late = [(d, k) for k, ds in edges.items() for d in ds if batch_of[d] > batch_of[k]]
    if late:
        raise InboxError(
            f"dependency {late[0][0]} sits in a later batch than {late[0][1]}, "
            "so it could never be approved in time"
        )
    return edges


def _check_cycle(edges: dict[str, list[str]]) -> None:
    marks: dict[str, int] = {}

    def visit(key: str, trail: tuple[str, ...]) -> None:
        if marks.get(key) == 1:
            raise InboxError(f"depends_on cycle: {' -> '.join((*trail, key))}")
        if marks.get(key) == 2:
            return
        marks[key] = 1
        for dep in edges.get(key, ()):
            visit(dep, (*trail, key))
        marks[key] = 2

    for key in sorted(edges):
        visit(key, ())


def load_inbox(path: str) -> Plan:
    root = os.path.abspath(path)
    manifest = _read_manifest(root)
    batch_size = manifest.get("batch_size", DEFAULT_BATCH_SIZE)
    if isinstance(batch_size, bool) or not isinstance(batch_size, int) or batch_size < 1:
        raise InboxError(f"batch_size must be an integer of 1 or more: {batch_size}")

    specs: dict[str, str] = {}
    files: dict[str, str] = {}
    batch_of: dict[str, int] = {}
    ordered: dict[str, list[tuple[str, int]]] = {}
    for repo in sorted(manifest["repos"]):
        spec = _entry(manifest, repo).get("spec")
        if not spec:
            raise InboxError(f"repo {repo} has no spec in manifest.json")
        specs[repo] = spec_path = os.path.abspath(os.path.join(root, str(spec)))
        if not os.path.isfile(spec_path):
            raise InboxError(f"spec file is missing: {spec_path}")
        found = _scan_tickets(root, repo)
        ordered[repo] = [(key, i // batch_size) for i, (key, _) in enumerate(found)]
        files.update(found)
        batch_of.update(ordered[repo])

    edges = _edges(manifest, batch_of)
    lanes = tuple(
        Lane(
            repo=repo,
            tickets=tuple(
                TicketState(
                    key=key, batch=batch, depends_on=tuple(sorted(edges.get(key, ())))
                )
                for key, batch in ordered[repo]
            ),
        )
        for repo in ordered
    )
    return Plan(
        State(prd=manifest["prd"], lanes=lanes),
        manifest["base"],
        batch_size,
        specs,
        files,
    )
