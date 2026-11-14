import pytest
from hypothesis import given, strategies as st

from watcher.adapters import DesktopNotifier, HkGate, LlamaSwapServer, OmpAgent
from watcher.config import Config, load_config
from watcher.plugins import PluginError, build_adapters, load_object

F = "tests.fakes.plugin"


def _cfg(**kw):
    return Config(models={}, **kw)


def test_AC1_defaults_build_builtin_adapters(tmp_path):
    cfg = load_config(str(tmp_path / "missing.toml"))
    a = build_adapters(cfg)
    assert isinstance(a.agent, OmpAgent)
    assert isinstance(a.gate, HkGate)
    assert isinstance(a.model_server, LlamaSwapServer)
    assert isinstance(a.notifier, DesktopNotifier)
    assert a.model_server.url == cfg.llm_url


def test_AC1_server_url_option_overrides_default():
    cfg = _cfg(options={"model_server": {"url": "http://x:1"}})
    assert build_adapters(cfg).model_server.url == "http://x:1"


def test_AC2_fake_agent_loaded_with_options_as_kwargs():
    cfg = _cfg(agent=f"{F}:FakeAgent", options={"agent": {"a": 1, "b": "two"}})
    a = build_adapters(cfg)
    assert type(a.agent).__name__ == "FakeAgent"
    assert a.agent.kwargs == {"a": 1, "b": "two"}


def test_AC2_all_roles_fakes():
    cfg = _cfg(
        agent=f"{F}:FakeAgent",
        gate=f"{F}:FakeGate",
        model_server=f"{F}:FakeServer",
        notifier=f"{F}:FakeNotifier",
        options={"notifier": {"k": 3}},
    )
    a = build_adapters(cfg)
    assert a.notifier.kwargs == {"k": 3}
    assert a.agent.kwargs == {}
    assert a.model_server.kwargs == {"url": cfg.llm_url}


def test_AC2_load_object_returns_class():
    assert load_object(f"{F}:FakeAgent").__name__ == "FakeAgent"


@pytest.mark.parametrize("spec", ["nocolon", "no.such:X", "watcher.config:Nope", "a:b:c"])
def test_AC3_load_object_errors_name_spec(spec):
    with pytest.raises(PluginError) as e:
        load_object(spec)
    assert spec in str(e.value)


def test_AC3_plugin_error_is_value_error():
    assert issubclass(PluginError, ValueError)


@given(st.text().filter(lambda s: s.count(":") != 1))
def test_AC3_property_bad_spec_raises(spec):
    with pytest.raises(PluginError):
        load_object(spec)


@pytest.mark.parametrize("role", ["agent", "gate", "model_server", "notifier"])
def test_AC4_missing_protocol_method(role):
    spec = f"{F}:FakeBrokenAgent"
    with pytest.raises(PluginError) as e:
        build_adapters(_cfg(**{role: spec}))
    assert "does not implement" in str(e.value)
    assert spec in str(e.value)
