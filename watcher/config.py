import os
import tomllib
from dataclasses import dataclass, field, fields

from watcher.types import PHASE_MODEL


@dataclass(frozen=True)
class Config:
    models: dict[str, str]
    llm_url: str = "http://127.0.0.1:9090"
    load_retry_wait: float = 60.0
    prompt_dir: str = ""
    agent: str = "watcher.adapters:OmpAgent"
    gate: str = "watcher.adapters:HkGate"
    model_server: str = "watcher.adapters:LlamaSwapServer"
    notifier: str = "watcher.adapters:DesktopNotifier"
    options: dict[str, dict] = field(default_factory=dict)


def default_path() -> str:
    env = os.environ.get("WATCHER_CONFIG")
    if env:
        return os.path.expanduser(env)
    base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(os.path.expanduser(base), "watcher", "watcher.toml")


def load_config(path: str | None = None) -> Config:
    path = path or default_path()
    data: dict = {}
    if os.path.exists(path):
        with open(path, "rb") as f:
            data = tomllib.load(f)
    known = {f.name for f in fields(Config)}
    for key in data:
        if key not in known:
            raise ValueError(f"unknown config key: {key}")
    models = {k: v for k, v in PHASE_MODEL.items() if k != "done"}
    models.update(data.pop("models", {}))
    kwargs = dict(data)
    if "WATCHER_LLM_URL" in os.environ:
        kwargs["llm_url"] = os.environ["WATCHER_LLM_URL"]
    if "WATCHER_LOAD_RETRY_WAIT" in os.environ:
        kwargs["load_retry_wait"] = float(os.environ["WATCHER_LOAD_RETRY_WAIT"])
    return Config(models=models, **kwargs)
