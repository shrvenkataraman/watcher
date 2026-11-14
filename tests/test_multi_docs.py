"""README section (multi-project ticket 08)."""
import pathlib

README = pathlib.Path(__file__).resolve().parent.parent / "README.md"


def _text():
    return README.read_text(encoding="utf-8")


def test_AC1_heading():
    assert "## Several projects at once" in _text()


def test_AC2_commands():
    t = _text()
    assert "watcher board --all" in t and "watcher prds" in t


def test_AC3_lease_dir():
    assert "watcher-leases" in _text()


def test_AC1_property_heading_once():
    assert _text().count("## Several projects at once") == 1
