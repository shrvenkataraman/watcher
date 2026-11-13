"""Parser for a reviewer verdict file.

`parse_verdict(path, commit)` reads a JSON verdict written by the reviewer and
returns a frozen `Verdict`, or raises `BadVerdict` with the reason.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

VERDICTS = ("APPROVED", "CHANGES")
FINDING_KEYS = ("id", "file", "symbol", "ac", "problem")
MIN_COMMIT_PREFIX = 7


class BadVerdict(ValueError):
    """The verdict file is missing, unreadable or malformed."""


@dataclass(frozen=True)
class Verdict:
    approved: bool
    findings_json: str


def _commit_matches(file_commit: Any, commit: str) -> bool:
    """True when the two commits are equal, or one is a prefix of the other."""
    if not isinstance(file_commit, str) or not isinstance(commit, str):
        return False
    if file_commit == commit:
        return True
    shorter = min(len(file_commit), len(commit))
    if shorter < MIN_COMMIT_PREFIX:
        return False
    return file_commit.startswith(commit) or commit.startswith(file_commit)


def _validate_finding(item: Any, index: int) -> None:
    if not isinstance(item, dict):
        raise BadVerdict(f"findings: finding {index} is not an object")
    for key in FINDING_KEYS:
        if key not in item:
            raise BadVerdict(f"findings: finding {index} is missing key {key!r}")
        if not isinstance(item[key], str):
            raise BadVerdict(f"findings: finding {index} key {key!r} is not a string")


def parse_verdict(path: str, commit: str) -> Verdict:
    """Parse the verdict file at `path` and check it against `commit`."""
    try:
        with open(path, encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise BadVerdict(f"verdict file is missing or unreadable: {path}: {exc}") from exc
    except UnicodeDecodeError as exc:
        raise BadVerdict(f"verdict file is not utf-8 text: {path}: {exc}") from exc

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise BadVerdict(f"verdict file is not valid json: {path}: {exc}") from exc

    if not isinstance(data, dict):
        raise BadVerdict("verdict: top level is not a json object")

    verdict = data.get("verdict")
    if "verdict" not in data:
        raise BadVerdict("verdict field is missing")
    if not isinstance(verdict, str) or verdict not in VERDICTS:
        raise BadVerdict(f"verdict must be one of {list(VERDICTS)}, got {verdict!r}")

    file_commit = data.get("commit")
    if "commit" not in data:
        raise BadVerdict("commit field is missing")
    if not isinstance(file_commit, str):
        raise BadVerdict(f"commit must be a string, got {type(file_commit).__name__}")
    if not _commit_matches(file_commit, commit):
        raise BadVerdict(f"commit mismatch: file has {file_commit!r}, expected {commit!r}")

    findings = data.get("findings")
    if "findings" not in data:
        raise BadVerdict("findings field is missing")
    if not isinstance(findings, list):
        raise BadVerdict(f"findings must be a list, got {type(findings).__name__}")
    for index, item in enumerate(findings):
        _validate_finding(item, index)

    if verdict == "CHANGES" and not findings:
        raise BadVerdict("findings must not be empty when verdict is CHANGES")

    return Verdict(
        approved=verdict == "APPROVED",
        findings_json=json.dumps(findings, sort_keys=True),
    )
