"""Scaffold gate: the package imports, the gate script exists, and uv serves pytest + hypothesis (ticket 00)."""
import os
import subprocess

import watcher

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_AC1_package_imports_with_version():
    assert watcher.__version__ == "0.1.0"


def test_AC2_gate_extra_exists_executable_and_parses():
    path = os.path.join(ROOT, ".claude", "gate-extra.sh")
    assert os.path.exists(path), ".claude/gate-extra.sh is missing"
    assert os.access(path, os.X_OK), ".claude/gate-extra.sh is not executable"
    assert subprocess.run(["bash", "-n", path], cwd=ROOT).returncode == 0


def test_AC3_uv_serves_pytest_and_hypothesis():
    for cmd in (["uv", "run", "pytest", "--version"], ["uv", "run", "python", "-c", "import hypothesis"]):
        assert subprocess.run(cmd, cwd=ROOT, capture_output=True).returncode == 0, cmd
