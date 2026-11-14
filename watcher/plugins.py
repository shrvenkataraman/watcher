import importlib

from watcher.config import Config
from watcher.ports import Adapters, Agent, Gate, ModelServer, Notifier

ROLES = (
    ("agent", Agent),
    ("gate", Gate),
    ("model_server", ModelServer),
    ("notifier", Notifier),
)


class PluginError(ValueError):
    pass


def load_object(spec: str) -> type:
    if spec.count(":") != 1:
        raise PluginError(f"bad plug-in spec (want module:Class): {spec!r}")
    mod_name, attr = spec.split(":")
    try:
        mod = importlib.import_module(mod_name)
    except Exception as e:
        raise PluginError(f"cannot import {spec}: {e}") from e
    try:
        return getattr(mod, attr)
    except AttributeError as e:
        raise PluginError(f"{spec}: no attribute {attr!r}") from e


def build_adapters(cfg: Config) -> Adapters:
    built = {}
    for role, proto in ROLES:
        spec = getattr(cfg, role)
        cls = load_object(spec)
        kwargs = dict(cfg.options.get(role, {}))
        if role == "model_server":
            kwargs.setdefault("url", cfg.llm_url)
        obj = cls(**kwargs)
        if not isinstance(obj, proto):
            raise PluginError(f"{spec} does not implement {proto.__name__}")
        built[role] = obj
    return Adapters(**built)
