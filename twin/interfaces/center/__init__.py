"""Command Center — TTY operator surface for Twin.

Launch: bare ``twin`` on a TTY. Non-TTY never enters the TUI.
Screens: Health · Services · MCP.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from twin.workspace import Workspace


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


def _looks_like_runtime_cmd(args: str) -> bool:
    """True when a process cmdline looks like ``twin runtime start``."""
    if "runtime" not in args or "start" not in args:
        return False
    if "twin.interfaces.cli" in args:
        return True
    tokens = args.split()
    for i, tok in enumerate(tokens):
        base = Path(tok).name
        if base in ("twin", "twin.exe"):
            rest = tokens[i + 1 :]
            if "runtime" in rest and "start" in rest:
                return True
    return False


def runtime_pids() -> list[int]:
    """Best-effort PIDs of ``twin runtime start`` workers (any home)."""
    pids: list[int] = []
    try:
        out = subprocess.check_output(
            ["ps", "-eo", "pid=,args="],
            text=True,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        return []
    me = os.getpid()
    for line in out.splitlines():
        line = line.strip()
        if not line:
            continue
        parts = line.split(None, 1)
        if len(parts) < 2:
            continue
        try:
            pid = int(parts[0])
        except ValueError:
            continue
        if pid == me:
            continue
        if _looks_like_runtime_cmd(parts[1]):
            pids.append(pid)
    return sorted(set(pids))


def serve_is_up(state: CenterState, port: int = DEFAULT_SERVE_PORT) -> bool:
    """True when Center's serve child is alive or something listens on ``port``."""
    if state.serve.proc and state.serve.proc.poll() is None:
        return True
    return bool(pids_listening_on(port))


def runtime_is_up(state: CenterState) -> bool:
    """True when Center's runtime child is alive or an external worker is found."""
    if state.runtime.proc and state.runtime.proc.poll() is None:
        return True
    return bool(runtime_pids())


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


def ensure_serve(state: CenterState, port: int = DEFAULT_SERVE_PORT) -> str:
    """Start serve only if nothing is already listening on ``port``."""
    url = f"http://127.0.0.1:{port}"
    state.serve.url = url
    if state.serve.proc and state.serve.proc.poll() is None:
        listeners = set(pids_listening_on(port))
        if not listeners or state.serve.proc.pid in listeners:
            return url
        # Child alive but not the listener — reclaim via start_serve.
        return start_serve(state, port=port)
    if pids_listening_on(port):
        # External serve already up — attach URL, do not kill/restart.
        return url
    return start_serve(state, port=port)


def ensure_runtime(state: CenterState) -> str:
    """Start runtime only if no worker (supervised or external) is running."""
    if state.runtime.proc and state.runtime.proc.poll() is None:
        return "attached"
    if runtime_pids():
        return "already"
    return start_runtime(state)


def stop_all_supervised(state: CenterState, port: int = DEFAULT_SERVE_PORT) -> None:
    stop_serve(state, port=port)
    stop_runtime(state)


def start_all_supervised(state: CenterState, port: int = DEFAULT_SERVE_PORT) -> dict[str, str]:
    """Start serve and runtime together — they are meant to run in parallel."""
    return {
        "serve": start_serve(state, port=port),
        "runtime": start_runtime(state),
    }


def ensure_all_supervised(state: CenterState, port: int = DEFAULT_SERVE_PORT) -> dict[str, str]:
    """Start serve + runtime only when they are not already running."""
    return {
        "serve": ensure_serve(state, port=port),
        "runtime": ensure_runtime(state),
    }


def launch_command_center(home: Optional[str] = None) -> int:
    """Run the Textual Command Center. Returns process exit code."""
    from twin.interfaces.center.app import TwinCenterApp

    ws = Workspace(home)
    state = CenterState(home=Path(ws.cfg.home))
    # Bring up HTTP/Web + job worker if missing; leave existing processes alone.
    ensure_all_supervised(state)
    app = TwinCenterApp(ws=ws, state=state)
    app.run()
    if state.exit_choice == "stop":
        stop_all_supervised(state)
    # leave / cancel: leave children running if any
    return 0
