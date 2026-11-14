import dataclasses
from pathlib import Path

from watcher import cli
from watcher.config import Config
from watcher.ports import Agent, Gate, ModelServer, Notifier

ROOT = Path(__file__).resolve().parent.parent


def _read(rel: str) -> str:
    p = ROOT / rel
    assert p.is_file(), f"missing {rel}"
    return p.read_text()


def test_AC1_readme_names_every_config_field():
    text = _read("README.md")
    fields = [f.name for f in dataclasses.fields(Config)]
    assert fields
    missing = [n for n in fields if n not in text]
    assert not missing, missing


def test_AC2_plugins_doc_names_every_protocol_method():
    text = _read("docs/plugins.md")
    methods = [m for P in (Agent, Gate, ModelServer, Notifier) for m in vars(P) if not m.startswith("_")]
    assert methods
    missing = [m for m in methods if m not in text]
    assert not missing, missing


def test_AC3_readme_names_every_cli_command():
    text = _read("README.md")
    commands = list(cli._parser()._subparsers._group_actions[0].choices)
    assert commands
    missing = [c for c in commands if c not in text]
    assert not missing, missing


def test_AC4_contributing_has_check_commands():
    text = _read("CONTRIBUTING.md")
    assert "uv run pytest -q" in text
    assert "cargo test --manifest-path kanban/Cargo.toml" in text
