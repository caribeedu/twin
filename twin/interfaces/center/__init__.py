"""Command Center — TTY operator surface for Twin (Sense / Cognize / Inject).

Launch: bare ``twin`` on a TTY. Non-TTY never enters the TUI.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from twin.workspace import Workspace

V2_VERBS = [
    "cognize run",
    "narrative search",
    "narrative commit",
    "narrative accessibility",
    "stance list",
    "inject pack",
    "review",
    "consolidate daily",
    "consolidate weekly",
    "connector list",
    "runtime status",
    "serve",
    "doctor",
    "research revisions",
]
LEGACY_ALIASES = [
    "extract",
    "meditate",
    "correlate",
    "judgment list",
    "memory unsupported",
]


@dataclass
class SupervisedProc:
    name: str
    proc: Optional[subprocess.Popen] = None
    url: str = ""
    log_path: Optional[Path] = None


@dataclass
class CenterState:
    home: Path
    serve: SupervisedProc = field(default_factory=lambda: SupervisedProc("serve"))
    runtime: SupervisedProc = field(default_factory=lambda: SupervisedProc("runtime"))
    exit_choice: str = ""  # stop | leave | cancel


def is_tty() -> bool:
    return bool(getattr(sys.stdin, "isatty", lambda: False)())


def should_launch_center(argv: Optional[list[str]]) -> bool:
    """True when invoked with no subcommand on a TTY."""
    args = list(sys.argv[1:] if argv is None else argv)
    # strip global --home PATH
    cleaned: list[str] = []
    i = 0
    while i < len(args):
        if args[i] == "--home" and i + 1 < len(args):
            i += 2
            continue
        if args[i].startswith("--home="):
            i += 1
            continue
        cleaned.append(args[i])
        i += 1
    return len(cleaned) == 0 and is_tty()


def home_snapshot(ws: Workspace) -> dict[str, Any]:
    backlog = 0
    try:
        backlog = len(ws.store.list_memories(status="candidate", limit=500))
    except Exception:
        pass
    reflections = 0
    if hasattr(ws.store, "list_open_reflections"):
        try:
            reflections = len(ws.store.list_open_reflections("default"))
        except Exception:
            pass
    halt = ""
    if hasattr(ws.store, "last_cognize_run"):
        try:
            run = ws.store.last_cognize_run()
            if run and run.get("halt_reason"):
                halt = str(run.get("halt_reason"))
        except Exception:
            pass
    connectors = 0
    if hasattr(ws.store, "list_connector_instances"):
        try:
            connectors = len(ws.store.list_connector_instances())
        except Exception:
            pass
    jobs_pending = 0
    if hasattr(ws.store, "runtime_queue_depth"):
        try:
            q = ws.store.runtime_queue_depth() or {}
            jobs_pending = int(q.get("pending") or q.get("ready") or 0)
        except Exception:
            pass
    return {
        "home": str(ws.home),
        "review_backlog": backlog,
        "open_reflections": reflections,
        "cognize_halt": halt,
        "connectors": connectors,
        "jobs_pending": jobs_pending,
    }


def fuzzy_palette(query: str) -> list[str]:
    q = (query or "").strip().lower()
    pool = list(V2_VERBS) + [f"(legacy) {a}" for a in LEGACY_ALIASES]
    if not q:
        return pool[:12]
    return [p for p in pool if q in p.lower()][:20]


def start_serve(state: CenterState, port: int = 8765) -> str:
    if state.serve.proc and state.serve.proc.poll() is None:
        return state.serve.url or f"http://127.0.0.1:{port}"
    log = state.home / "logs" / "center-serve.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    state.serve.log_path = log
    state.serve.proc = subprocess.Popen(
        [sys.executable, "-c",
         "from twin.interfaces.cli import main; main()",
         "serve", "--home", str(state.home), "--port", str(port)],
        stdout=log.open("a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    state.serve.url = f"http://127.0.0.1:{port}"
    return state.serve.url


def stop_serve(state: CenterState) -> None:
    if state.serve.proc and state.serve.proc.poll() is None:
        try:
            os.killpg(state.serve.proc.pid, signal.SIGTERM)
        except Exception:
            state.serve.proc.terminate()
    state.serve.proc = None


def start_runtime(state: CenterState) -> str:
    if state.runtime.proc and state.runtime.proc.poll() is None:
        return "attached"
    log = state.home / "logs" / "center-runtime.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    state.runtime.log_path = log
    state.runtime.proc = subprocess.Popen(
        [sys.executable, "-c",
         "from twin.interfaces.cli import main; main()",
         "runtime", "start", "--home", str(state.home), "--no-live"],
        stdout=log.open("a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    return "started"


def stop_runtime(state: CenterState) -> None:
    if state.runtime.proc and state.runtime.proc.poll() is None:
        try:
            os.killpg(state.runtime.proc.pid, signal.SIGTERM)
        except Exception:
            state.runtime.proc.terminate()
    state.runtime.proc = None


def stop_all_supervised(state: CenterState) -> None:
    stop_serve(state)
    stop_runtime(state)


def launch_command_center(home: Optional[str] = None) -> int:
    """Run the Textual Command Center. Returns process exit code."""
    from twin.interfaces.center.app import TwinCenterApp

    ws = Workspace(home)
    state = CenterState(home=Path(ws.home))
    app = TwinCenterApp(ws=ws, state=state)
    app.run()
    if state.exit_choice == "stop":
        stop_all_supervised(state)
    # leave / cancel: leave children running if any
    return 0
