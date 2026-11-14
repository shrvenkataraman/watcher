import pytest
from hypothesis import given, settings, strategies as st, HealthCheck

from watcher.config import Config, load_config

DEFAULT_MODELS = {
    "flash": "qwen3.8-flash-next",
    "review": "qwen3.8-27b-w8a8",
    "pr": "glm-5.3-flash-maya",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("WATCHER_LLM_URL", "WATCHER_LOAD_RETRY_WAIT", "WATCHER_CONFIG"):
        monkeypatch.delenv(k, raising=False)


def _write(tmp_path, text):
    p = tmp_path / "w.toml"
    p.write_text(text)
    return str(p)


def test_AC1_missing_file_gives_defaults(tmp_path):
    cfg = load_config(str(tmp_path / "nope.toml"))
    assert cfg == Config(models=dict(DEFAULT_MODELS))
    assert cfg.llm_url == "http://127.0.0.1:9090"
    assert cfg.load_retry_wait == 60.0
    assert cfg.prompt_dir == ""
    assert cfg.agent == "watcher.adapters:OmpAgent"
    assert cfg.gate == "watcher.adapters:HkGate"
    assert cfg.model_server == "watcher.adapters:LlamaSwapServer"
    assert cfg.notifier == "watcher.adapters:DesktopNotifier"
    assert cfg.options == {}


def test_AC2_models_table_merges_over_defaults(tmp_path):
    cfg = load_config(_write(tmp_path, '[models]\nreview = "x"\n'))
    assert cfg.models == {**DEFAULT_MODELS, "review": "x"}


@given(
    given_=st.dictionaries(
        st.sampled_from(["flash", "review", "pr"]),
        st.text(alphabet="abcdefghij0123456789.-", min_size=1, max_size=12),
    )
)
@settings(max_examples=40, suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_AC2_property_subset_merges(tmp_path_factory, given_):
    d = tmp_path_factory.mktemp("c")
    body = "[models]\n" + "".join(f'{k} = "{v}"\n' for k, v in given_.items())
    p = d / "w.toml"
    p.write_text(body)
    assert load_config(str(p)).models == {**DEFAULT_MODELS, **given_}


def test_AC3_unknown_key_raises_value_error(tmp_path):
    with pytest.raises(ValueError, match="bogus_key"):
        load_config(_write(tmp_path, 'bogus_key = 1\n'))


def test_AC4_env_overrides_file(tmp_path, monkeypatch):
    p = _write(tmp_path, 'llm_url = "http://file:1"\nload_retry_wait = 5.0\n')
    monkeypatch.setenv("WATCHER_LLM_URL", "http://env:2")
    monkeypatch.setenv("WATCHER_LOAD_RETRY_WAIT", "7.5")
    cfg = load_config(p)
    assert cfg.llm_url == "http://env:2"
    assert cfg.load_retry_wait == 7.5


def test_AC5_options_tables(tmp_path):
    cfg = load_config(_write(tmp_path, '[options.omp]\nprovider = "p"\n'))
    assert cfg.options == {"omp": {"provider": "p"}}
