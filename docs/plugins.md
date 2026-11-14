# Plug-in guide

watcher has four roles. Each role is a Python Protocol in `watcher/ports.py`. You replace a role by writing a class with the same methods and naming it in `watcher.toml`.

## How a plug-in is found

The config value is `module:Class`, for example `agent = "mypkg.agent:MyAgent"`. watcher imports `module` and reads `Class`. A value with no single colon, a failed import or a missing name raises `PluginError`.

watcher then builds the object with keyword arguments from `[options.<role>]`. The role names are `agent`, `gate`, `model_server` and `notifier`. For `model_server`, `url` defaults to `llm_url`. The object must pass an `isinstance` check against the Protocol. Otherwise watcher raises `PluginError`. Accept `**_` in `__init__` so extra options do not fail.

```toml
agent = "mypkg.agent:MyAgent"

[options.agent]
timeout = 600
```

The module must be importable by the Python that runs `watcher`.

## Agent

Runs one agent role in a worktree and reports its outcome.

- `run(role, model, worktree, prompt_file, task) -> AgentResult`
  - `role`: the role to play, for example implement or review.
  - `model`: model name for the phase.
  - `worktree`: directory to work in.
  - `prompt_file`: path to the system prompt file.
  - `task`: the task text.
  - Returns `AgentResult(outcome, detail)`. Both are strings.

Built-in: `watcher.agents:CommandAgent`. It runs any CLI from an `argv` template with the fields `{role} {model} {prompt_file} {task} {worktree} {tools}`. Options: `argv`, `timeout` (default 1200), `edit_tools`, `read_tools`.

```toml
agent = "watcher.agents:CommandAgent"
[options.agent]
argv = ["pi", "-p", "--model", "{model}", "--tools", "{tools}", "--append-system-prompt", "{prompt_file}", "{task}"]
edit_tools = "read,edit,write,bash"
read_tools = "read,grep,find,write"
```

Example:

```python
import subprocess
from watcher.ports import AgentResult

class EchoAgent:
    def __init__(self, binary="my-agent", **_):
        self.binary = binary

    def run(self, role, model, worktree, prompt_file, task):
        p = subprocess.run([self.binary, "--model", model, "--prompt", prompt_file, task],
                           cwd=worktree, capture_output=True, text=True)
        outcome = "ok" if p.returncode == 0 else "error"
        return AgentResult(outcome, (p.stdout + p.stderr)[-500:])
```

## Gate

Provides lane worktrees and the verify and review checks.

- `lane_worktree(root, prd, repo) -> str`: return the worktree path for a lane. Do not create it.
- `ensure_lane(prd, repo, base, check, root) -> str`: create the lane worktree if missing, store the check command, return the path.
- `verify(worktree) -> GateResult`: run the check. Return `GateResult(ok, tail)`. `tail` is the end of the output.
- `review(worktree) -> GateResult`: run the independent review. Same result type.

Built-in: `watcher.gates:GitGate`. It uses plain `git worktree`, and `verify` runs the check command with bash. Its `review` always passes. Options: `repos_dir`, `worktrees_dir`, `timeout` (default 1200). The default gate `watcher.adapters:HkGate` uses `hk`.

Example:

```python
import subprocess
from watcher.ports import GateResult

class MakeGate:
    def __init__(self, **_): pass

    def lane_worktree(self, root, prd, repo):
        return f"{root}/{prd}/{repo}"

    def ensure_lane(self, prd, repo, base, check, root):
        return self.lane_worktree(root, prd, repo)

    def verify(self, worktree):
        p = subprocess.run(["make", "test"], cwd=worktree, capture_output=True, text=True)
        return GateResult(p.returncode == 0, p.stdout[-2000:])

    def review(self, worktree):
        return GateResult(True, "no review")
```

## ModelServer

Makes a named model ready to serve and says whether it is.

- `ensure_model(name) -> bool`: return True when the model is ready. Return False when it is not. Do not raise for a down server.

Built-in: `watcher.servers:OpenAIServer`. It checks `GET <url>/v1/models` for the model id. Options: `url` (default `http://127.0.0.1:8000`, overridden by `llm_url` when unset), `api_key_env` (name of an environment variable that holds the key), `timeout` (default 60). The default `watcher.adapters:LlamaSwapServer` loads models through llama-swap.

Example:

```python
class AlwaysReady:
    def __init__(self, **_): pass

    def ensure_model(self, name):
        return True
```

## Notifier

Delivers a message to a human.

- `notify(title, body) -> None`: show or send the message.

Built-in alternative: `watcher.adapters:DesktopNotifier` (the default).

Example:

```python
import sys

class StderrNotifier:
    def __init__(self, **_): pass

    def notify(self, title, body):
        print(f"{title}: {body}", file=sys.stderr)
```
