"""tick passes cfg.prompt_dir to the executor as Ctx.templates (watcher ticket 16)."""
import glob
import os

import watcher.loop as loopmod
import watcher.prompts as prompts
from tests.test_loop_config import _cfg, _inbox
from watcher.config import Config
from watcher.types import Event


def _tick_and_prompt(base, prompt_dir):
    """Drive tick; on each implement action write the prompt the executor would write."""
    seen = []

    def fake_execute(action, ctx):
        seen.append(ctx)
        if action.kind == "implement":
            prompts.write_prompt("implement", ctx.prompt_dir, key=action.key,
                                 templates=ctx.templates)
        if action.kind == "load_model":
            return Event("model_ready", detail=action.model)
        return None

    orig = loopmod.executor.execute
    loopmod.executor.execute = fake_execute
    try:
        cfg = _cfg()
        cfg = Config(**{**cfg.__dict__, "prompt_dir": prompt_dir}) if hasattr(cfg, "__dict__") else cfg
        inbox = _inbox(base)
        for _ in range(4):
            loopmod.tick("prd1", inbox, os.path.join(base, "work"),
                         state_root=os.path.join(base, "state"), cfg=cfg)
    finally:
        loopmod.executor.execute = orig
    return seen


def _rules(base):
    files = glob.glob(os.path.join(base, "state", "**", "prompts", "implement-*.md"), recursive=True)
    assert files, "no implement prompt written"
    with open(files[0], encoding="utf-8") as f:
        return f.read().split("## Rules\n", 1)[1].strip()


def test_AC1_custom_prompt_dir_sets_rules_section(tmp_path):
    custom = tmp_path / "tpl"
    custom.mkdir()
    (custom / "implement.md").write_text("Custom rule.\n")
    seen = _tick_and_prompt(str(tmp_path), str(custom))
    assert seen and all(c.templates == str(custom) for c in seen)
    assert _rules(str(tmp_path)) == "Custom rule."


def test_AC2_empty_prompt_dir_uses_builtin_rule(tmp_path):
    seen = _tick_and_prompt(str(tmp_path), "")
    assert seen and all(c.templates == "" for c in seen)
    assert _rules(str(tmp_path)) == prompts.EDIT_RULE
