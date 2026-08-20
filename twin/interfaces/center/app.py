"""Textual Command Center application — Twin brand TUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Header, Label, Static

from twin.interfaces.center import (
    CenterState,
    DEFAULT_SERVE_PORT,
    pids_listening_on,
    read_log_tail,
    runtime_is_up,
    serve_is_up,
    start_all_supervised,
    start_runtime,
    start_serve,
    stop_all_supervised,
    stop_runtime,
    stop_serve,
)
from twin.interfaces.center import actions
from twin.workspace import Workspace

# Twin brand (aligned with twin/interfaces/web/static/app.css)
_TWIN_CSS = """
$twin-purple: #4f3d9e;
$twin-deep: #252526;
$twin-soft: #7b6bc4;
$twin-mist: #e8e8e8;
$twin-ink: #1e1e1e;
$twin-panel: #252526;
$twin-line: #3c3c3c;
$twin-muted: #9a94b0;
$twin-ok: #2f9d6a;
$twin-warn: #c9842a;
$twin-err: #c44b5a;

Screen {
    background: $twin-ink;
    color: $twin-mist;
}
Header {
    background: #181818;
    color: $twin-mist;
    text-style: bold;
    dock: top;
    height: 1;
}
Button {
    background: $twin-panel;
    color: $twin-mist;
    border: tall $twin-line;
    margin-right: 1;
    margin-bottom: 0;
}
Button:hover {
    background: $twin-purple;
    color: $twin-mist;
}
Button.-primary {
    background: $twin-purple;
    color: $twin-mist;
    border: tall $twin-soft;
    text-style: bold;
}
Button.-error {
    background: $twin-err;
    color: $twin-mist;
    border: tall $twin-err;
}

#shell {
    height: 1fr;
    width: 100%;
}
#main-col {
    width: 1fr;
    height: 1fr;
    padding: 1 2;
}
#mcp-rail {
    width: 36;
    height: 1fr;
    padding: 1 1 1 0;
    background: #1a1a1a;
}
.page-title {
    color: $twin-soft;
    text-style: bold;
    margin-bottom: 0;
}
.page-sub {
    color: $twin-muted;
    margin-bottom: 1;
}
.section-title {
    color: $twin-soft;
    text-style: bold;
    margin-bottom: 0;
    margin-top: 0;
}
.panel {
    background: $twin-panel;
    border: tall $twin-line;
    padding: 1 2;
    margin-bottom: 1;
    height: auto;
}
#services-box {
    background: $twin-panel;
    border: tall $twin-line;
    padding: 1 2;
    margin-bottom: 1;
    height: auto;
}
#services-box .toolbar {
    margin-top: 1;
    width: 100%;
    height: auto;
}
#services-box Button {
    width: 1fr;
    margin-right: 1;
}
#mcp-rail .panel {
    height: 1fr;
    margin-bottom: 0;
}
.hint {
    color: $twin-muted;
    margin-top: 1;
    text-align: center;
}
.toolbar {
    height: auto;
    margin-bottom: 0;
}
.body {
    height: 1fr;
}

#exit-dialog {
    background: $twin-panel;
    border: tall $twin-soft;
    padding: 1 2;
    width: 64;
    height: auto;
    color: $twin-mist;
}
#exit-dialog Label {
    color: $twin-soft;
    text-style: bold;
    margin-bottom: 1;
}
"""


def _alive(proc) -> bool:
    return bool(proc and proc.poll() is None)


def _status_markup(running: bool, running_label: str = "running", stopped: str = "stopped") -> str:
    if running:
        return f"[bold #2f9d6a]{running_label}[/]"
    return f"[#9a94b0]{stopped}[/]"


class ExitPrompt(ModalScreen[str]):
    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Leave Command Center"),
            Static(
                "Stop supervised [bold #7b6bc4]web[/] + [bold #7b6bc4]runtime[/] "
                "children, or leave them running?",
                classes="page-sub",
            ),
            Horizontal(
                Button("Yes — stop", id="stop", variant="error"),
                Button("Leave running", id="leave", variant="primary"),
                Button("Cancel", id="cancel"),
            ),
            id="exit-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id or "cancel")


class LogViewer(ModalScreen[None]):
    BINDINGS = [Binding("escape", "app.pop_screen", "Close", show=False)]

    def __init__(self, title: str, path: Optional[Path], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._path = path

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(classes="page", id="main-col"):
            yield Label(self._title, classes="page-title")
            yield Static(
                str(self._path) if self._path else "(no log path)",
                classes="page-sub",
            )
            with VerticalScroll(classes="body"):
                yield Static(read_log_tail(self._path), id="log-body", classes="panel")


class MainScreen(Screen):
    """Single operator surface: Health + Services + MCP rail."""

    BINDINGS = [
        Binding("q", "quit_center", "Quit", show=False),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="shell"):
            with Vertical(id="main-col"):
                yield Label("Command Center", classes="page-title")
                yield Static(
                    "Manage your instance",
                    classes="page-sub",
                )
                yield Label("Health", classes="section-title")
                yield Static(id="health-body", classes="panel")
                yield Label("Services", classes="section-title")
                with Vertical(id="services-box"):
                    yield Static(id="services-status")
                    with Horizontal(classes="toolbar"):
                        yield Button("Start both", id="start-both", variant="primary")
                        yield Button("Stop both", id="stop-both", variant="error")
                        yield Button("Start web", id="start-serve")
                        yield Button("Stop web", id="stop-serve")
                    with Horizontal(classes="toolbar"):
                        yield Button("Start runtime", id="start-runtime")
                        yield Button("Stop runtime", id="stop-runtime")
                        yield Button("Web logs", id="log-serve")
                        yield Button("Runtime logs", id="log-runtime")
            with Vertical(id="mcp-rail"):
                yield Label("MCP", classes="page-title")
                yield Static("Host tools · install status", classes="page-sub")
                yield Static(id="mcp-body", classes="panel")
                yield Static("[#9a94b0]q[/] to quit", classes="hint")

    def on_mount(self) -> None:
        self._ensure_log_paths()
        self.refresh_all()

    def on_screen_resume(self) -> None:
        self.refresh_all()

    def action_quit_center(self) -> None:
        self.app.action_quit_center()

    def _ensure_log_paths(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        logs = app.state.home / "logs"
        if app.state.serve.log_path is None:
            app.state.serve.log_path = logs / "center-serve.log"
        if app.state.runtime.log_path is None:
            app.state.runtime.log_path = logs / "center-runtime.log"

    def refresh_all(self) -> None:
        self._refresh_health()
        self._refresh_services()
        self._refresh_mcp()

    def _refresh_health(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        doc = actions.doctor_summary(app.ws)
        ok = int(doc.get("checks_ok") or 0)
        total = int(doc.get("checks_total") or 0)
        doctor_cls = "ok" if ok == total and total else ("warn" if ok else "err")
        tone = {
            "ok": "#2f9d6a",
            "warn": "#c9842a",
            "err": "#c44b5a",
        }.get(doctor_cls, "#9a94b0")
        warns = doc.get("warnings") or []
        warn_lines = "\n".join(
            f"  [#c9842a]![/] {w.get('name')}: {w.get('detail')}" for w in warns[:12]
        ) or "  [#2f9d6a]✓[/] no warnings"
        self.query_one("#health-body", Static).update(
            f"[bold #7b6bc4]doctor[/]  [{tone}]{ok}/{total} ok[/]\n"
            f"  llm        {doc.get('llm') or '—'}\n"
            f"  extractor  {doc.get('extractor') or '—'}\n"
            f"  embedder   {doc.get('embedder') or '—'}\n"
            f"[#9a94b0]  {doc.get('home') or ''}[/]\n\n"
            f"[bold #7b6bc4]checks[/]\n{warn_lines}"
        )

    def _refresh_services(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        port = DEFAULT_SERVE_PORT
        listeners = pids_listening_on(port)
        serve_child = _alive(app.state.serve.proc)
        serve_alive = serve_is_up(app.state, port)
        rt_alive = runtime_is_up(app.state)
        rt_label = (
            "attached" if _alive(app.state.runtime.proc)
            else "running" if rt_alive
            else "stopped"
        )
        mode = (
            "both running" if serve_alive and rt_alive
            else "partial" if serve_alive or rt_alive
            else "stopped"
        )
        mode_color = "#2f9d6a" if mode == "both running" else (
            "#c9842a" if mode == "partial" else "#9a94b0"
        )
        if serve_alive and not app.state.serve.url:
            app.state.serve.url = f"http://127.0.0.1:{port}"
        web_label = (app.state.serve.url or "running") if serve_alive else "running"
        pids: list[int] = []
        if serve_child and app.state.serve.proc is not None:
            pids.append(int(app.state.serve.proc.pid))
        for pid in listeners:
            if pid not in pids:
                pids.append(pid)
        pid_line = (
            f"\n  [#9a94b0]pid[/]      {', '.join(map(str, pids))}"
            if pids else "\n  [#9a94b0]pid[/]      —"
        )
        self.query_one("#services-status", Static).update(
            f"[bold #7b6bc4]status[/]  [{mode_color}]{mode}[/]\n"
            f"  runtime   {_status_markup(rt_alive, running_label=rt_label)}\n"
            f"  web       {_status_markup(serve_alive, running_label=web_label)}"
            f"{pid_line}"
        )

    def _refresh_mcp(self) -> None:
        rows = actions.mcp_client_status()
        lines = ["[bold #7b6bc4]providers[/]"]
        for row in rows:
            if row["installed"]:
                mark = "[bold #2f9d6a]installed[/]"
            else:
                mark = "[#9a94b0]not installed[/]"
            lines.append(f"  {row['label']}")
            lines.append(f"  {mark}  [#9a94b0]{row['path']}[/]")
        self.query_one("#mcp-body", Static).update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        bid = event.button.id
        if bid == "start-both":
            out = start_all_supervised(app.state)
            self.notify(f"web {out['serve']} · runtime {out['runtime']}")
        elif bid == "stop-both":
            stop_all_supervised(app.state)
            self.notify("stopped web + runtime")
        elif bid == "start-serve":
            url = start_serve(app.state)
            alive = _alive(app.state.serve.proc) or bool(pids_listening_on(DEFAULT_SERVE_PORT))
            self.notify(
                f"web at {url}" if alive else "web failed — check Web logs",
                severity="information" if alive else "error",
            )
        elif bid == "stop-serve":
            stop_serve(app.state)
            self.notify("web stopped · port freed")
        elif bid == "start-runtime":
            self.notify(f"runtime {start_runtime(app.state)}")
        elif bid == "stop-runtime":
            stop_runtime(app.state)
        elif bid == "log-serve":
            self._ensure_log_paths()
            self.app.push_screen(LogViewer("Web logs", app.state.serve.log_path))
            return
        elif bid == "log-runtime":
            self._ensure_log_paths()
            self.app.push_screen(LogViewer("Runtime logs", app.state.runtime.log_path))
            return
        self.refresh_all()


class TwinCenterApp(App[None]):
    TITLE = "twin"
    SUB_TITLE = "Command Center"
    CSS = _TWIN_CSS
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, ws: Workspace, state: CenterState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ws = ws
        self.state = state

    def on_mount(self) -> None:
        self.push_screen(MainScreen())

    def action_quit_center(self) -> None:
        def done(choice: Optional[str]) -> None:
            if choice in ("stop", "leave"):
                self.state.exit_choice = choice or "leave"
                self.exit()

        self.push_screen(ExitPrompt(), done)
