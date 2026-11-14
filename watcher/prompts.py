"""Prompt writer: one markdown file per omp run (watcher ticket 15).

`write_prompt(role, out_dir, ...)` builds the text for one role, writes it to
`<out_dir>/<role>-<key with / -> _>.md` and returns that path plus the task line
the orchestrator sends to omp. A section appears only when its input is
non-empty, and the sections keep the order the role table lists them in.
"""

from __future__ import annotations

import os

# A section input names either a file to read or a value to paste.
FILE_INPUTS = ("ticket", "spec")

# Each role lists its sections as (heading, input name) in the order they appear.
SECTIONS: dict[str, tuple[tuple[str, str], ...]] = {
    "implement": (("## Ticket", "ticket"), ("## Previous failure", "failure")),
    "fix": (("## Ticket", "ticket"), ("## Findings", "findings")),
    "review": (("## Ticket", "ticket"), ("## Commit", "commit")),
    "pr_review": (("## Spec", "spec"), ("## Diff", "diff"), ("## Verdicts", "verdicts")),
    "pr_fix": (("## Spec", "spec"), ("## Findings", "findings")),
}

TASK: dict[str, str] = {
    "implement": "Implement the ticket now.",
    "fix": "Fix the findings now.",
    "review": "Review the commit now.",
    "pr_review": "Review the PR now.",
    "pr_fix": "Fix the PR findings now.",
}

RULES_HEADER = "## Rules"
# The same three sentences carry every role that edits files.
EDIT_RULE = (
    "Edit only files in the ticket's Edit line. Do not commit. If you cannot "
    "proceed without a decision, write the question to .agent/question.md and stop."
)
FIX_RULE = f"{EDIT_RULE} Fix only these findings."
READ_RULE = (
    "Do not edit files. Write .agent/pr-verdict.json in the same verdict format "
    "with commit set to HEAD."
)
REVIEW_RULE = (
    "Run git show {commit}. Do not edit files. Write {verdict_file} with keys "
    "verdict, commit, findings; each finding has id, file, symbol, ac, problem."
)
VERDICT_FILE = ".agent/verdicts/{nn}.json"


def _read(path: str) -> str:
    """Return the text of a file; empty when the caller gave no path."""
    if not path:
        return ""
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def _nn(key: str) -> str:
    """Return the part of a ticket key after the last slash: 'quark-kit/03' -> '03'."""
    return key.rsplit("/", 1)[-1]


def _rules(role: str, *, commit: str, nn: str) -> str:
    """Return the rule text for one role."""
    if role in ("fix", "pr_fix"):
        return FIX_RULE
    if role == "review":
        return REVIEW_RULE.format(
            commit=commit, verdict_file=VERDICT_FILE.format(nn=nn)
        )
    if role == "pr_review":
        return READ_RULE
    return EDIT_RULE


def write_prompt(
    role: str,
    out_dir: str,
    *,
    ticket_file: str = "",
    spec_file: str = "",
    findings: str = "",
    failure: str = "",
    commit: str = "",
    diff: str = "",
    verdicts: str = "",
    key: str = "",
) -> tuple[str, str]:
    """Write the prompt file for one run; return (path, task)."""
    try:
        sections = SECTIONS[role]
        task = TASK[role]
    except KeyError:
        raise ValueError(f"unknown prompt role: {role}") from None

    inputs = {
        "ticket": ticket_file,
        "spec": spec_file,
        "findings": findings,
        "failure": failure,
        "commit": commit,
        "diff": diff,
        "verdicts": verdicts,
    }

    parts = [f"# Role: {role}"]
    for heading, name in sections:
        given = inputs[name]
        body = _read(given) if name in FILE_INPUTS else given
        if body:
            parts.append(f"{heading}\n{body.strip()}")
    parts.append(f"{RULES_HEADER}\n{_rules(role, commit=commit, nn=_nn(key))}")

    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, f"{role}-{key.replace('/', '_')}.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write("\n\n".join(parts) + "\n")
    return path, task
