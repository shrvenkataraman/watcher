"""CLI: watcher status|inbox|show|answer|retry|skip|abort|run|tick|tui|prds (tickets 19, 22, 25, 03).

Commands read state.json and never write it. User input appends one Event line to queue.jsonl.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from typing import Callable

from . import loop, newinbox, store, tui
from .config import load_config
from .status import render_text, status_doc
from .types import Event, NeedsYou, State, TicketState, to_json

EXIT_OK, EXIT_USAGE, EXIT_NEEDS_YOU = 0, 2, 3
DETAIL_CHARS = 60
PROG = "watcher"
KEY_HELP = "ticket key, for example quark-kit/07"
WORK_ROOT = os.environ.get("WATCHER_WORK", os.path.expanduser("~/Work"))
BOARD_BIN = os.environ.get("WATCHER_BOARD", "watcher-kanban")


def _resolve_prd(prd: str | None, root: str | None) -> tuple[str | None, str]:
    """Return the prd to act on, or None plus the message that explains why not."""
    if prd is not None:
        return prd, ""
    parent = os.path.dirname(store.state_dir("", root))
    dirs = [n for n in (os.listdir(parent) if os.path.isdir(parent) else [])
            if os.path.isdir(os.path.join(parent, n))]
    if len(dirs) == 1:
        return dirs[0], ""
    return None, "no state for prd" if not dirs else "ambiguous prd: " + " ".join(sorted(dirs))


def _fail(message: str) -> int:
    """Print a command failure on stderr and return the usage exit code."""
    print(message, file=sys.stderr)
    return EXIT_USAGE


def _load(args: argparse.Namespace) -> tuple[State | None, int]:
    """Resolve --prd/--state-root and load that state, or return the error exit code."""
    prd, message = _resolve_prd(args.prd, args.state_root)
    if prd is None:
        return None, _fail(message)
    state = store.load(prd, args.state_root)
    return (state, EXIT_OK) if state is not None else (None, _fail("no state for prd"))


def _append(path: str, text: str) -> None:
    """Append text to a file, creating its directory first, then fsync it."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a", encoding="utf-8") as handle:
        handle.write(text)
        handle.flush()
        os.fsync(handle.fileno())


def _queue(state: State, args: argparse.Namespace, event: Event) -> int:
    """Queue one event as one line of queue.jsonl; state.json is never written."""
    queue = os.path.join(store.state_dir(state.prd, args.state_root), "queue.jsonl")
    _append(queue, json.dumps(to_json(event)) + "\n")
    return EXIT_OK


def _find(state: State, key: str) -> tuple[TicketState | None, list[NeedsYou]]:
    """Return the ticket with this key in any lane, plus the needs-you entries with it."""
    tickets = [t for lane in state.lanes for t in lane.tickets if t.key == key]
    return (tickets[0] if tickets else None), [n for n in state.needs_you if n.key == key]


def _cmd_status(state: State, args: argparse.Namespace) -> int:
    """Print the status view as text, or as JSON with --json."""
    doc = status_doc(state)
    print(json.dumps(doc, indent=2, sort_keys=True) if args.json else render_text(doc))
    return EXIT_OK


def _cmd_inbox(state: State, args: argparse.Namespace) -> int:
    """Print only the NEEDS YOU block; exit 3 when it holds an item, else 0."""
    needs = status_doc(state)["needs_you"]
    rows = [f"  {n['key']}  {n['reason']}  {n['detail'][:DETAIL_CHARS]}" for n in needs]
    print("\n".join([f"NEEDS YOU ({len(needs)})"] + rows))
    return EXIT_NEEDS_YOU if needs else EXIT_OK


def _cmd_show(state: State, args: argparse.Namespace) -> int:
    """Print one ticket's status, sha and findings plus its needs-you entries."""
    ticket, needs = _find(state, args.key)
    if ticket is None and not needs:
        return _fail(f"unknown key: {args.key}")
    head = [] if ticket is None else [
        f"{args.key}  status={ticket.status}  sha={ticket.sha or '-'}",
        f"findings: {ticket.findings or '-'}",
    ]
    print("\n".join(head + [f"needs_you {n.reason}: {n.detail}" for n in needs]))
    return EXIT_OK


def _cmd_prds(args: argparse.Namespace) -> int:
    """Print every project that has state as one JSON line; never read --prd."""
    print(json.dumps({"schema": 1, "prds": store.list_prds(args.state_root)}))
    return EXIT_OK


def _key_command(kind: str, answer: bool = False) -> Callable:
    """Build a command that queues this event kind for a key the state already knows."""

    def run(state: State, args: argparse.Namespace) -> int:
        ticket, needs = _find(state, args.key)
        if ticket is None and not needs:
            return _fail(f"unknown key: {args.key}")
        if answer:
            answers = os.path.join(store.state_dir(state.prd, args.state_root), "answers")
            _append(os.path.join(answers, args.key.replace("/", "_") + ".md"),
                    "\n\n## Answer\n" + args.text)
        return _queue(state, args, Event(kind, args.key))

    return run


_COMMANDS: dict[str, Callable] = {
    "status": _cmd_status, "inbox": _cmd_inbox, "show": _cmd_show,
    "abort": lambda state, args: _queue(state, args, Event("abort")),
    "answer": _key_command("answered", answer=True),
    "retry": _key_command("retry"), "skip": _key_command("skip"),
}


def _strip_prog(argv: list[str] | None) -> list[str] | None:
    """Return argv without its leading program name, which some callers include."""
    return argv[1:] if argv and argv[0] == PROG else argv


def _parser() -> argparse.ArgumentParser:
    """Build the parser: one subcommand, each taking --prd and --state-root."""
    parser = argparse.ArgumentParser(prog=PROG)
    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--prd", default=None, help="prd name (default: the only one)")
    common.add_argument("--state-root", default=None, help="state root holding watcher/")
    common.add_argument("--config", default=None, help="watcher.toml path (default: $WATCHER_CONFIG or ~/.config/watcher/watcher.toml)")
    sub = parser.add_subparsers(dest="command", required=True)
    new = sub.add_parser("new", help="build an inbox from a ticket bundle")
    new.add_argument("--from", dest="bundle", required=True, help="bundle directory")
    new.add_argument("--repo", required=True, help="repo name")
    new.add_argument("--prd", required=True, help="prd name")
    new.add_argument("--check", required=True, help="check command")
    new.add_argument("--base", default="develop", help="base branch")
    new.add_argument("--inbox-root", default=None, help="inbox root (default: <work>/inbox)")
    for name, help_text, keys in (
        ("status", "print the status view", ""), ("inbox", "print the NEEDS YOU block", ""),
        ("show", "print one ticket", "key"), ("retry", "retry one ticket", "key"),
        ("skip", "skip one ticket", "key"), ("answer", "answer one question", "key text"),
        ("abort", "abort the run", ""),
        ("run", "tick until the run is done", ""), ("tick", "advance one round", ""),
        ("tui", "open the terminal UI", ""),
        ("board", "open the kanban board", ""),
        ("prds", "list the projects that have state", ""),
    ):
        child = sub.add_parser(name, parents=[common], help=help_text)
        for arg in keys.split():
            child.add_argument(arg, help=KEY_HELP if arg == "key" else "the answer text")
        if name == "board":
            child.add_argument("--all", action="store_true", help="show every project")
        if name == "status":
            child.add_argument("--json", action="store_true", help="print the status JSON")
        if name in ("run", "tick"):
            child.add_argument("--inbox", required=True, help="inbox directory to read")
    return parser


def main(argv: list[str] | None = None) -> int:
    """Run one CLI command and return its exit code."""
    args = _parser().parse_args(_strip_prog(argv))
    if args.command == "new":
        root = args.inbox_root or os.path.join(WORK_ROOT, "inbox")
        try:
            path = newinbox.build_inbox(args.bundle, args.repo, args.prd, args.check, root,
                                        base=args.base)
        except (FileExistsError, ValueError, OSError) as err:
            return _fail(str(err))
        print(path)
        return EXIT_OK
    if args.command == "prds":
        return _cmd_prds(args)
    if args.command == "tui":
        prd, message = _resolve_prd(args.prd, args.state_root)
        return _fail(message) if prd is None else tui.main(prd)
    if args.command == "board":
        if args.all and args.prd:
            return _fail("watcher board: use --prd or --all, not both")
        if args.all:
            prd_args = ["--all"]
        else:
            prd, message = _resolve_prd(args.prd, args.state_root)
            if prd is None:
                return _fail(message)
            prd_args = ["--prd", prd]
        if shutil.which(BOARD_BIN) is None:
            return _fail("watcher board: install the board with `cargo install --path kanban`")
        extra = ["--state-root", args.state_root] if args.state_root else []
        os.execvp(BOARD_BIN, [BOARD_BIN, *prd_args, *extra])
        return EXIT_OK
    if args.command in ("run", "tick"):  # these two step the pipeline; the rest read it
        if args.prd is None:
            return _fail("--prd is required for run and tick")
        cfg = load_config(args.config)
        if args.command == "run":
            return loop.run(args.prd, args.inbox, WORK_ROOT, state_root=args.state_root, cfg=cfg)
        loop.tick(args.prd, args.inbox, WORK_ROOT, state_root=args.state_root, cfg=cfg)
        return EXIT_OK
    state, code = _load(args)
    return code if state is None else _COMMANDS[args.command](state, args)
