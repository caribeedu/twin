"""Command Center — TTY operator surface for Twin (Sense / Cognize / Inject).

Launch: bare ``twin`` on a TTY. Non-TTY never enters the TUI.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from twin.workspace import Workspace

PALETTE_VERBS = [
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
        backlog = len(ws.store.list_claims(status="candidate", limit=500))
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
        "home": str(ws.cfg.home),
        "review_backlog": backlog,
        "open_reflections": reflections,
        "cognize_halt": halt,
        "connectors": connectors,
        "jobs_pending": jobs_pending,
    }


def fuzzy_palette(query: str) -> list[str]:
    q = (query or "").strip().lower()
    pool = list(PALETTE_VERBS)
    if not q:
        return pool[:12]
    return [p for p in pool if q in p.lower()][:20]


DEFAULT_SERVE_PORT = 8765


def pids_listening_on(port: int) -> list[int]:
    """PIDs with a TCP LISTEN socket on ``port`` (best-effort, no extra deps)."""
    pids: list[int] = []
    try:
        out = subprocess.check_output(
            ["lsof", f"-tiTCP:{port}", "-sTCP:LISTEN"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        pids.extend(int(x) for x in out.split() if x.strip().isdigit())
    except Exception:
        pass
    if pids:
        return sorted(set(pids))
    try:
        out = subprocess.check_output(
            ["ss", "-tlnp", f"sport = :{port}"],
            text=True,
            stderr=subprocess.DEVNULL,
        )
        import re
        for m in re.finditer(r"pid=(\d+)", out):
            pids.append(int(m.group(1)))
    except Exception:
        pass
    return sorted(set(pids))


def free_listen_port(port: int, *, exclude: Optional[set[int]] = None) -> list[int]:
    """SIGTERM then SIGKILL listeners on ``port``. Returns killed PIDs."""
    exclude = exclude or set()
    killed: list[int] = []
    for pid in pids_listening_on(port):
        if pid in exclude or pid == os.getpid():
            continue
        try:
            os.kill(pid, signal.SIGTERM)
            killed.append(pid)
        except ProcessLookupError:
            continue
        except Exception:
            continue
    if killed:
        time.sleep(0.35)
    still = [p for p in pids_listening_on(port) if p not in exclude and p != os.getpid()]
    for pid in still:
        try:
            os.kill(pid, signal.SIGKILL)
            if pid not in killed:
                killed.append(pid)
        except Exception:
            pass
    if still:
        time.sleep(0.2)
    return killed


def read_log_tail(path: Optional[Path], *, lines: int = 120) -> str:
    if path is None or not Path(path).exists():
        return "(no log file yet)"
    try:
        text = Path(path).read_text(encoding="utf-8", errors="replace")
    except Exception as exc:
        return f"(failed to read log: {exc})"
    parts = text.splitlines()
    if not parts:
        return "(empty log)"
    return "\n".join(parts[-lines:])


def start_serve(state: CenterState, port: int = DEFAULT_SERVE_PORT) -> str:
    if state.serve.proc and state.serve.proc.poll() is None:
        # Tracked child alive — but port may still be held by an orphan.
        if not pids_listening_on(port) or (
            state.serve.proc.pid in pids_listening_on(port)
        ):
            # If our child isn't the listener, reclaim the port and restart.
            listeners = set(pids_listening_on(port))
            if state.serve.proc.pid in listeners or not listeners:
                return state.serve.url or f"http://127.0.0.1:{port}"
        stop_serve(state, port=port)
    else:
        # Drop stale handle; free orphan listeners before bind.
        state.serve.proc = None
        free_listen_port(port)

    log = state.home / "logs" / "center-serve.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    state.serve.log_path = log
    # Global --home must precede the subcommand (argparse parent options).
    state.serve.proc = subprocess.Popen(
        [
            sys.executable, "-c",
            "from twin.interfaces.cli import main; main()",
            "--home", str(state.home),
            "serve", "--port", str(port),
        ],
        stdout=log.open("a"),
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    state.serve.url = f"http://127.0.0.1:{port}"
    # Brief wait so bind errors surface in poll().
    time.sleep(0.6)
    if state.serve.proc.poll() is not None:
        # Failed — often address-in-use; reclaim and retry once.
        free_listen_port(port)
        state.serve.proc = subprocess.Popen(
            [
                sys.executable, "-c",
                "from twin.interfaces.cli import main; main()",
                "--home", str(state.home),
                "serve", "--port", str(port),
            ],
            stdout=log.open("a"),
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        time.sleep(0.6)
    return state.serve.url


def stop_serve(state: CenterState, port: int = DEFAULT_SERVE_PORT) -> None:
    if state.serve.proc and state.serve.proc.poll() is None:
        try:
            os.killpg(state.serve.proc.pid, signal.SIGTERM)
        except Exception:
            try:
                state.serve.proc.terminate()
            except Exception:
                pass
    state.serve.proc = None
    # Always clear the port — orphans from prior Center sessions break restart.
    free_listen_port(port)


def start_runtime(state: CenterState) -> str:
    if state.runtime.proc and state.runtime.proc.poll() is None:
        return "attached"
    log = state.home / "logs" / "center-runtime.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    state.runtime.log_path = log
    state.runtime.proc = subprocess.Popen(
        [
            sys.executable, "-c",
            "from twin.interfaces.cli import main; main()",
            "--home", str(state.home),
            "runtime", "start", "--no-live",
        ],
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


def stop_all_supervised(state: CenterState, port: int = DEFAULT_SERVE_PORT) -> None:
    stop_serve(state, port=port)
    stop_runtime(state)


def start_all_supervised(state: CenterState, port: int = DEFAULT_SERVE_PORT) -> dict[str, str]:
    """Start serve and runtime together — they are meant to run in parallel."""
    return {
        "serve": start_serve(state, port=port),
        "runtime": start_runtime(state),
    }


def launch_command_center(home: Optional[str] = None) -> int:
    """Run the Textual Command Center. Returns process exit code."""
    from twin.interfaces.center.app import TwinCenterApp

    ws = Workspace(home)
    state = CenterState(home=Path(ws.cfg.home))
    app = TwinCenterApp(ws=ws, state=state)
    app.run()
    if state.exit_choice == "stop":
        stop_all_supervised(state)
    # leave / cancel: leave children running if any
    return 0
