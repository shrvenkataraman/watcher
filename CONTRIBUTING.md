# Contributing

## Dev setup

```
uv sync
```

This installs the dev tools (pytest, hypothesis, pytest-cov, diff-cover, mutmut). Python 3.13 or newer is needed. The kanban board needs a Rust toolchain.

## Checks

Run both before you open a PR.

```
uv run pytest -q
cargo test --manifest-path kanban/Cargo.toml
```

CI runs the same checks.

## Rules

- Keep the core pure. `core.step` does no I/O. It takes a state and an event and returns a new state and a list of actions. The executor and the adapters do the I/O.
- Keep the reference model in step. `tests/ref/model.py` changes with any core rule change, in the same PR.
- The 4 waves stay fixed in core. Only models, prompts and plug-ins are configurable.
- Add a `Config` field, a Protocol method or a CLI command only with its docs. `tests/test_docs.py` fails when README.md or docs/plugins.md misses a name.

## Where things are

- `watcher/`: the Python package. `watcher/ports.py` holds the plug-in Protocols.
- `kanban/`: the Rust kanban board, binary `watcher-kanban`. It reads `state.json` and follows `schema/status-v1.json`.
- `tests/`: Python tests. `tests/fakes/` holds fake plug-ins and fake CLI tools.
- `docs/plugins.md`: the plug-in guide.

## Pull requests

- Use a branch named `feat/`, `fix/` or `chore/`.
- Keep a PR small and on one topic.
- Add or update tests with the change. Do not edit a test only to make it pass.
- Both checks must pass.
- Describe why the change is needed, not only what changed.
