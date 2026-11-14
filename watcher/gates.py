"""GitGate: lane worktrees and verify without hk."""
import os
import subprocess

from watcher.ports import GateResult


class GitGate:
    def __init__(self, repos_dir: str = "", worktrees_dir: str = "", timeout: float = 1200, **_):
        self.repos_dir = repos_dir
        self.worktrees_dir = worktrees_dir
        self.timeout = timeout

    def lane_worktree(self, root, prd, repo) -> str:
        return os.path.join(self.worktrees_dir or os.path.join(root, "features"), prd, repo)

    def ensure_lane(self, prd, repo, base, check, root) -> str:
        path = self.lane_worktree(root, prd, repo)
        if os.path.exists(path):
            return path
        src = os.path.join(self.repos_dir or os.path.join(root, "repos"), repo)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        subprocess.run(["git", "-C", src, "worktree", "add", "-b", f"feat/{prd}", path, base],
                       capture_output=True, text=True, check=True)
        os.makedirs(os.path.join(path, ".agent"), exist_ok=True)
        with open(os.path.join(path, ".agent", "check"), "w") as f:
            f.write(check.strip() + "\n")
        return path

    def verify(self, worktree) -> GateResult:
        with open(os.path.join(worktree, ".agent", "check")) as f:
            cmd = f.read()
        try:
            p = subprocess.run(["bash", "-c", cmd], cwd=worktree, capture_output=True,
                               text=True, timeout=self.timeout)
        except subprocess.TimeoutExpired:
            return GateResult(False, f"timed out after {self.timeout}s")
        out = (p.stdout or "") + (p.stderr or "")
        return GateResult(p.returncode == 0, "\n".join(out.splitlines()[-40:]))

    def review(self, worktree) -> GateResult:
        return GateResult(True, "no review gate")
