# watcher - no-LLM wave runner for local-model ticket pipelines

watcher runs a bundle of tickets through local models. watcher itself calls no LLM. It only schedules work, runs checks and records state.

## What it does

A run has four waves.

1. flash: a fast model implements each ticket in a lane worktree.
2. review: a review model reads each implemented ticket and approves it or asks for changes.
3. fix: the flash model fixes the findings. The ticket then goes back to review.
4. pr: a PR model opens the pull request when all tickets are approved.

```
inbox --> [flash] --> [review] --+--> [pr] --> done
              ^                  |
              +-----[fix]<-------+  (changes requested)
```

Questions that need a human go to the NEEDS YOU list (`watcher inbox`).

## Install

```
uv tool install .
```

This installs the `watcher` command. It needs Python 3.13 or newer.

Install the kanban board binary (`watcher-kanban`) with Rust:

```
cargo install --path kanban
```

## Quick start

1. Build an inbox from a directory of ticket files:

   ```
   watcher new --from ./tickets --repo myrepo --prd myprd --check "uv run pytest -q"
   ```

   The command prints the inbox path.

2. Run the pipeline until it is done (use `tick` to advance one round):

   ```
   watcher run --prd myprd --inbox <inbox path>
   ```

3. Watch progress from another terminal:

   ```
   watcher status --prd myprd
   watcher prds
   watcher board --prd myprd
   ```

   `watcher board` starts the kanban binary `watcher-kanban`. `watcher tui` opens a terminal UI instead.

If only one prd exists, you can leave out `--prd`. To try the pipeline without real models, point `agent`, `gate`, `model_server` and `notifier` at your own plug-ins (see `docs/plugins.md`).

## Configuration

watcher reads `watcher.toml` from `--config`, then `$WATCHER_CONFIG`, then `$XDG_CONFIG_HOME/watcher/watcher.toml` (default `~/.config/watcher/watcher.toml`). A missing file means all defaults. An unknown key is an error.

Environment overrides: `WATCHER_LLM_URL` sets `llm_url`. `WATCHER_LOAD_RETRY_WAIT` sets `load_retry_wait`. `WATCHER_WORK` sets the work root (default `~/Work`). `WATCHER_BOARD` sets the kanban binary name.

Full example with every field at its default:

```toml
llm_url = "http://127.0.0.1:9090"
load_retry_wait = 60.0
prompt_dir = ""
agent = "watcher.adapters:OmpAgent"
gate = "watcher.adapters:HkGate"
model_server = "watcher.adapters:LlamaSwapServer"
notifier = "watcher.adapters:DesktopNotifier"

[models]
flash = "qwen3.8-flash-next"
review = "qwen3.8-27b-w8a8"
pr = "glm-5.3-flash-maya"

# Options passed to a plug-in constructor, one table per role.
[options.agent]
```

Field reference:

| Field | Meaning |
| --- | --- |
| `models` | Map of phase (`flash`, `review`, `pr`) to model name. Your entries replace the defaults one by one. |
| `llm_url` | Base URL of the model server. Passed to the model server plug-in as `url`. |
| `load_retry_wait` | Seconds to wait before retrying when a model fails to load. |
| `prompt_dir` | Directory of prompt templates that replace the built-in ones. Empty means built-in. |
| `agent` | `module:Class` of the Agent plug-in. It runs one agent role. |
| `gate` | `module:Class` of the Gate plug-in. It makes lane worktrees and runs verify and review. |
| `model_server` | `module:Class` of the ModelServer plug-in. It makes a model ready. |
| `notifier` | `module:Class` of the Notifier plug-in. It tells a human. |
| `options` | Map of role name to constructor keyword arguments, written as `[options.agent]`, `[options.gate]`, `[options.model_server]`, `[options.notifier]`. |

## Commands

Every command except `new` accepts `--prd`, `--state-root` and `--config`.

| Command | What it does |
| --- | --- |
| `new` | Build an inbox from a ticket bundle. Needs `--from`, `--repo`, `--prd`, `--check`. Optional: `--base` (default `develop`), `--inbox-root`. |
| `status` | Print the status view. `--json` prints JSON. |
| `inbox` | Print the NEEDS YOU block. Exit code 3 when it has items. |
| `show KEY` | Print one ticket: status, sha, findings and open questions. |
| `retry KEY` | Queue a retry of one ticket. |
| `skip KEY` | Queue a skip of one ticket. |
| `answer KEY TEXT` | Record an answer to a question and queue it. |
| `abort` | Queue an abort of the run. |
| `run` | Tick until the run is done. Needs `--inbox`. |
| `tick` | Advance one round. Needs `--inbox`. |
| `tui` | Open the terminal UI. |
| `board` | Open the kanban board (`watcher-kanban`). |

A KEY looks like `quark-kit/07`. Commands that read state never write `state.json`. User input is appended to `queue.jsonl`.

## Several projects at once

Each project is one `--prd` with its own `watcher run`. Runs share the GPU
through a model lease: runs that need the same model go together, and a run
that needs another model waits until the first model is free. Lock files live
in `<state root>/watcher-leases`.

Show every project on one board:

    watcher board --all

`r` retries and `s` skips the ticket under the cursor, in its own project.
`watcher prds` prints the projects that have state, as JSON.

## Plug-ins

watcher has four plug-in roles. See `docs/plugins.md`.

## Contributing

See `CONTRIBUTING.md`.

## License

MIT. See `LICENSE`.
