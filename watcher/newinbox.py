"""Build an inbox directory from a grill-to-local ticket bundle."""

from __future__ import annotations

import json
import os
import re
import shutil

_BLOCKED = re.compile(r"^\*\*Blocked by:\*\*[ \t]*(.*)$", re.M)
_NAME = re.compile(r"^(\d{2})-.+\.md$")


def _blockers(text: str) -> list[str]:
    match = _BLOCKED.search(text)
    if not match or match.group(1).strip().lower() in ("", "none"):
        return []
    return [f"{int(n):02d}" for n in re.findall(r"\d+", match.group(1))]


def build_inbox(bundle: str, repo: str, prd: str, check: str, out: str,
                base: str = "develop", batch_size: int = 5) -> str:
    """Write out/<prd> from the bundle and return its path; never overwrite."""
    issues = os.path.join(bundle, "issues")
    names = sorted(n for n in os.listdir(issues) if _NAME.match(n))
    known = {_NAME.match(n).group(1) for n in names}
    depends: dict[str, list[str]] = {}
    for name in names:
        with open(os.path.join(issues, name), encoding="utf-8") as handle:
            blocked = _blockers(handle.read())
        for nn in blocked:
            if nn not in known:
                raise ValueError(f"{name} is blocked by {nn}, which is not in the bundle")
        if blocked:
            depends[_NAME.match(name).group(1)] = [f"{repo}/{nn}" for nn in blocked]

    root = os.path.join(out, prd)
    os.makedirs(out, exist_ok=True)
    os.mkdir(root)
    spec = os.path.join(bundle, "spec.md")
    os.makedirs(os.path.join(root, "specs"))
    os.makedirs(os.path.join(root, "tickets", repo))
    shutil.copyfile(spec, os.path.join(root, "prd.md"))
    shutil.copyfile(spec, os.path.join(root, "specs", f"{repo}.md"))
    for name in names:
        shutil.copyfile(os.path.join(issues, name), os.path.join(root, "tickets", repo, name))
    manifest = {"prd": prd, "base": base, "batch_size": batch_size, "check": check,
                "repos": {repo: {"spec": f"specs/{repo}.md", "check": check,
                                 "depends_on": depends}}}
    with open(os.path.join(root, "manifest.json"), "w", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
    return root
