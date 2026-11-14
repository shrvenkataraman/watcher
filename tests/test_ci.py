"""Static text checks for .github/workflows/ci.yml (no PyYAML)."""
import re
from pathlib import Path

CI = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "ci.yml"


def _text() -> str:
    assert CI.is_file(), f"missing {CI}"
    return CI.read_text()


def _job_block(text: str, name: str) -> str:
    m = re.search(rf"^  {name}:\n((?:    .*\n|\n)*)", text, re.M)
    assert m, f"job {name} missing"
    return m.group(1)


def test_AC1_jobs_and_run_lines_present():
    text = _text()
    py = _job_block(text, "python")
    kb = _job_block(text, "kanban")
    for block in (py, kb):
        assert "runs-on: ubuntu-latest" in block
        assert "uses: actions/checkout@v4" in block
    assert "uses: astral-sh/setup-uv@v5" in py
    assert "run: uv sync" in py
    assert "run: uv run pytest -q" in py
    assert "uses: dtolnay/rust-toolchain@stable" in kb
    assert "run: cargo test --manifest-path kanban/Cargo.toml" in kb


def test_AC2_test_commands_present():
    text = _text()
    assert "uv run pytest -q" in text
    assert "cargo test --manifest-path kanban/Cargo.toml" in text


def test_AC3_triggers_push_and_pull_request():
    text = _text()
    m = re.search(r"^(?:on|\"on\"|true):\s*(.*)$", text, re.M)
    assert m, "no on: key"
    inline = m.group(1)
    start = m.end()
    rest = text[start:].split("\njobs:")[0]
    section = inline + "\n" + rest
    assert re.search(r"\bpush\b", section)
    assert re.search(r"\bpull_request\b", section)
