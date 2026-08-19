"""Textual Command Center application — Twin brand TUI."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Grid, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static

from twin.interfaces.center import (
    CenterState,
    DEFAULT_SERVE_PORT,
    fuzzy_palette,
    home_snapshot,
    pids_listening_on,
    read_log_tail,
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
Footer {
    background: #181818;
    color: $twin-muted;
    dock: bottom;
}
Button {
    background: $twin-panel;
    color: $twin-mist;
    border: tall $twin-line;
    margin-right: 1;
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
Input {
    background: $twin-panel;
    color: $twin-mist;
    border: tall $twin-line;
    padding: 0 1;
}
Input:focus {
    border: tall $twin-soft;
}
ListView {
    background: $twin-panel;
    border: tall $twin-line;
    height: 1fr;
}
ListItem {
    padding: 0 1;
}
ListItem > Label {
    color: $twin-mist;
}
ListItem.-highlight {
    background: $twin-purple;
}

.page {
    padding: 1 2;
    height: 1fr;
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
.panel {
    background: $twin-panel;
    border: tall $twin-line;
    padding: 1 2;
    margin-bottom: 1;
    height: auto;
}
.panel-title {
    color: $twin-soft;
    text-style: bold;
    margin-bottom: 1;
}
.metrics {
    grid-size: 4;
    grid-gutter: 1 1;
    height: auto;
    margin-bottom: 1;
}
.metric {
    background: $twin-panel;
    border: tall $twin-line;
    padding: 1 1;
    height: 5;
}
.metric-label {
    color: $twin-muted;
    text-style: bold;
}
.metric-value {
    color: $twin-mist;
    text-style: bold;
}
.metric-value.ok { color: $twin-ok; }
.metric-value.warn { color: $twin-warn; }
.metric-value.err { color: $twin-err; }
.metric-value.soft { color: $twin-soft; }
.toolbar {
    height: auto;
    margin-bottom: 1;
}
.body {
    height: 1fr;
}
.hint {
    color: $twin-muted;
    margin-top: 1;
}
.status-ok { color: $twin-ok; text-style: bold; }
.status-warn { color: $twin-warn; text-style: bold; }
.status-err { color: $twin-err; text-style: bold; }
.status-soft { color: $twin-soft; }

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
#cognize-confirm {
    background: $twin-panel;
    border: tall $twin-soft;
    padding: 1 2;
    width: 72;
    height: auto;
    color: $twin-mist;
}
#cognize-confirm Label {
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
                "Stop supervised [bold #7b6bc4]serve[/] + [bold #7b6bc4]runtime[/] "
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


def _format_cognize_estimate(est: dict[str, Any]) -> str:
    priced = est.get("priced")
    cost_line = (
        f"~${est.get('cost_usd_est', 0):.4f}  "
        f"(range ${est.get('cost_usd_low', 0):.4f}–${est.get('cost_usd_high', 0):.4f})"
        if priced
        else "unpriced model — add rates in pricing.json"
    )
    stages = " → ".join(est.get("stages") or []) or "—"
    return (
        f"[bold #7b6bc4]model[/]  {est.get('model') or '—'}  "
        f"[#9a94b0]({est.get('provider') or '—'})[/]\n"
        f"[bold #7b6bc4]tokenizer[/]  {est.get('tokenizer') or '—'}\n"
        f"[bold #7b6bc4]percepts[/]  {est.get('percepts', 0)}  ·  "
        f"until {est.get('until') or '—'}\n"
        f"[#9a94b0]stages[/]  {stages}\n\n"
        f"[bold #7b6bc4]tokens[/]  in {est.get('input_tokens', 0):,}  ·  "
        f"out ~{est.get('output_tokens_est', 0):,}  "
        f"(range {est.get('output_tokens_low', 0):,}–{est.get('output_tokens_high', 0):,})\n"
        f"[bold #7b6bc4]cost[/]  {cost_line}\n\n"
        f"[#9a94b0]{est.get('disclaimer') or 'Estimate only.'}[/]"
    )


class CognizeConfirm(ModalScreen[bool]):
    """Show preflight estimate; run only if the user confirms."""

    BINDINGS = [Binding("escape", "cancel", "Cancel")]

    def __init__(self, estimate: dict[str, Any], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._estimate = estimate

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Confirm cognize (queue to runtime)"),
            Static(_format_cognize_estimate(self._estimate), classes="page-sub"),
            Horizontal(
                Button("Queue cognize", id="confirm", variant="primary"),
                Button("Cancel", id="cancel"),
            ),
            id="cognize-confirm",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id == "confirm")

    def action_cancel(self) -> None:
        self.dismiss(False)


class LogViewer(ModalScreen[None]):
    """Tail of a supervised service log."""

    BINDINGS = [Binding("escape", "app.pop_screen", "Close")]

    def __init__(self, title: str, path: Optional[Path], **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._title = title
        self._path = path

    def compose(self) -> ComposeResult:
        with Vertical(classes="page"):
            yield Label(self._title, classes="page-title")
            yield Static(str(self._path or "—"), classes="page-sub")
            with Horizontal(classes="toolbar"):
                yield Button("Refresh", id="log-refresh", variant="primary")
                yield Button("Close", id="log-close")
            yield VerticalScroll(Static(id="log-body", classes="panel"), classes="body")

    def on_mount(self) -> None:
        self._reload()

    def _reload(self) -> None:
        self.query_one("#log-body", Static).update(read_log_tail(self._path))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "log-refresh":
            self._reload()
        elif event.button.id == "log-close":
            self.app.pop_screen()


class _NavMixin:
    """Shared screen navigation bindings used from Home."""

    def action_goto_services(self) -> None:
        self.app.push_screen(ServicesScreen())

    def action_goto_connectors(self) -> None:
        self.app.push_screen(ConnectorsScreen())

    def action_goto_jobs(self) -> None:
        self.app.push_screen(JobsScreen())

    def action_goto_cognize(self) -> None:
        self.app.push_screen(CognizeScreen())

    def action_goto_review(self) -> None:
        self.app.push_screen(ReviewScreen())

    def action_goto_browse(self) -> None:
        self.app.push_screen(BrowseScreen())

    def action_goto_mcp(self) -> None:
        self.app.push_screen(McpScreen())

    def action_palette(self) -> None:
        self.app.push_screen(PaletteScreen())

    def action_quit_center(self) -> None:
        self.app.action_quit_center()


class HomeScreen(_NavMixin, Screen):
    BINDINGS = [
        Binding("s", "goto_services", "Services"),
        Binding("c", "goto_connectors", "Connectors"),
        Binding("j", "goto_jobs", "Jobs"),
        Binding("g", "goto_cognize", "Cognize"),
        Binding("r", "goto_review", "Review"),
        Binding("b", "goto_browse", "Browse"),
        Binding("m", "goto_mcp", "MCP"),
        Binding("slash", "palette", "Palette"),
        Binding("q", "quit_center", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            yield Label("twin", classes="page-title")
            yield Static("Command Center · Sense → Cognize → Inject", classes="page-sub")
            yield Grid(
                Static(id="m-doctor", classes="metric"),
                Static(id="m-review", classes="metric"),
                Static(id="m-reflect", classes="metric"),
                Static(id="m-jobs", classes="metric"),
                classes="metrics",
            )
            yield Static(id="home-services", classes="panel")
            yield Static(id="home-health", classes="panel")
            yield Static(
                "[#9a94b0]s[/] services  [#9a94b0]c[/] connectors  [#9a94b0]j[/] jobs  "
                "[#9a94b0]g[/] cognize  [#9a94b0]r[/] review  [#9a94b0]b[/] browse  "
                "[#9a94b0]m[/] mcp  [#9a94b0]/[/] palette  "
                "[#9a94b0]q[/] quit",
                classes="hint",
            )
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_home()

    def on_screen_resume(self) -> None:
        # Returning from Services / other screens — re-read supervised procs.
        self.refresh_home()

    def refresh_home(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        snap = home_snapshot(app.ws)
        doc = actions.doctor_summary(app.ws)
        serve_on = _alive(app.state.serve.proc)
        runtime_on = _alive(app.state.runtime.proc)
        ok = int(doc.get("checks_ok") or 0)
        total = int(doc.get("checks_total") or 0)
        doctor_cls = "ok" if ok == total and total else ("warn" if ok else "err")
        backlog = snap["review_backlog"]
        refs = snap["open_reflections"]
        jobs = snap["jobs_pending"]

        def metric(label: str, value: str, tone: str, sub: str) -> str:
            tone_color = {
                "ok": "#2f9d6a",
                "warn": "#c9842a",
                "err": "#c44b5a",
                "soft": "#7b6bc4",
            }.get(tone, "#ebe7f8")
            return (
                f"[bold #9a94b0]{label}[/]\n"
                f"[bold {tone_color}]{value}[/]\n"
                f"[#9a94b0]{sub}[/]"
            )

        self.query_one("#m-doctor", Static).update(
            metric(
                "doctor",
                f"{ok}/{total} ok",
                doctor_cls,
                f"{doc.get('llm') or '—'} · {doc.get('extractor') or '—'}",
            )
        )
        self.query_one("#m-review", Static).update(
            metric(
                "review",
                str(backlog),
                "warn" if backlog else "ok",
                "candidates awaiting human",
            )
        )
        self.query_one("#m-reflect", Static).update(
            metric("reflections", str(refs), "soft", "open epistemic gaps")
        )
        self.query_one("#m-jobs", Static).update(
            metric(
                "jobs",
                str(jobs),
                "warn" if jobs else "ok",
                f"{snap['connectors']} connectors",
            )
        )

        mode = (
            "both running" if serve_on and runtime_on
            else "partial" if serve_on or runtime_on
            else "stopped"
        )
        mode_color = "#2f9d6a" if mode == "both running" else (
            "#c9842a" if mode == "partial" else "#9a94b0"
        )
        self.query_one("#home-services", Static).update(
            f"[bold #7b6bc4]services[/]  [{mode_color}]{mode}[/]\n"
            f"  serve    {_status_markup(serve_on, running_label=app.state.serve.url or 'running')}\n"
            f"  runtime  {_status_markup(runtime_on)}\n"
            f"[#9a94b0]  press s · Start both runs HTTP/Web + job worker together[/]"
        )

        warns = doc.get("warnings") or []
        halt = snap.get("cognize_halt") or ""
        warn_lines = "\n".join(
            f"  [#c9842a]![/] {w.get('name')}: {w.get('detail')}" for w in warns[:5]
        ) or "  [#2f9d6a]✓[/] no warnings"
        halt_line = (
            f"\n  [#c44b5a]halt[/] {halt}" if halt else "\n  [#2f9d6a]cognize[/] ready"
        )
        self.query_one("#home-health", Static).update(
            f"[bold #7b6bc4]health[/]  [#9a94b0]{snap['home']}[/]\n"
            f"{warn_lines}{halt_line}"
        )


class ServicesScreen(Screen):
    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back"),
        Binding("q", "app.pop_screen", "Back"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            yield Label("Services", classes="page-title")
            yield Static(
                "serve (HTTP / Web Center) and runtime (jobs) run in parallel",
                classes="page-sub",
            )
            with Horizontal(classes="toolbar"):
                yield Button("Start both", id="start-both", variant="primary")
                yield Button("Stop both", id="stop-both", variant="error")
            with Horizontal(classes="toolbar"):
                yield Button("Start serve", id="start-serve")
                yield Button("Stop serve", id="stop-serve")
                yield Button("Start runtime", id="start-runtime")
                yield Button("Stop runtime", id="stop-runtime")
            with Horizontal(classes="toolbar"):
                yield Button("Serve logs", id="log-serve")
                yield Button("Runtime logs", id="log-runtime")
            yield Static(id="services-status", classes="panel")
        yield Footer()

    def on_mount(self) -> None:
        self._ensure_log_paths()
        self._refresh()

    def _ensure_log_paths(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        logs = app.state.home / "logs"
        if app.state.serve.log_path is None:
            app.state.serve.log_path = logs / "center-serve.log"
        if app.state.runtime.log_path is None:
            app.state.runtime.log_path = logs / "center-runtime.log"

    def _refresh(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        port = DEFAULT_SERVE_PORT
        listeners = pids_listening_on(port)
        serve_child = _alive(app.state.serve.proc)
        serve_listening = bool(listeners)
        serve_alive = serve_child or serve_listening
        rt_alive = _alive(app.state.runtime.proc)
        mode = (
            "both running" if serve_alive and rt_alive
            else "partial" if serve_alive or rt_alive
            else "stopped"
        )
        mode_color = "#2f9d6a" if mode == "both running" else (
            "#c9842a" if mode == "partial" else "#9a94b0"
        )
        if serve_alive:
            serve_label = app.state.serve.url or "running"
        else:
            serve_label = "running"
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
            f"[bold #7b6bc4]status[/]  [{mode_color}]{mode}[/]\n\n"
            f"  runtime   {_status_markup(rt_alive, running_label='attached')}\n"
            f"  serve     {_status_markup(serve_alive, running_label=serve_label)}"
            f"{pid_line}"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        bid = event.button.id
        if bid == "start-both":
            out = start_all_supervised(app.state)
            self.notify(f"serve {out['serve']} · runtime {out['runtime']}")
        elif bid == "stop-both":
            stop_all_supervised(app.state)
            self.notify("stopped serve + runtime")
        elif bid == "start-serve":
            url = start_serve(app.state)
            alive = _alive(app.state.serve.proc) or bool(pids_listening_on(DEFAULT_SERVE_PORT))
            self.notify(
                f"serve at {url}" if alive else "serve failed — check Serve logs",
                severity="information" if alive else "error",
            )
        elif bid == "stop-serve":
            stop_serve(app.state)
            self.notify("serve stopped · port freed")
        elif bid == "start-runtime":
            self.notify(f"runtime {start_runtime(app.state)}")
        elif bid == "stop-runtime":
            stop_runtime(app.state)
        elif bid == "log-serve":
            self._ensure_log_paths()
            self.app.push_screen(LogViewer("Serve logs", app.state.serve.log_path))
            return
        elif bid == "log-runtime":
            self._ensure_log_paths()
            self.app.push_screen(LogViewer("Runtime logs", app.state.runtime.log_path))
            return
        self._refresh()


class ConnectorsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            yield Label("Connectors", classes="page-title")
            yield Static("Sense I/O — test, pause, resume", classes="page-sub")
            yield Input(placeholder="connector id", id="connector-id")
            with Horizontal(classes="toolbar"):
                yield Button("Refresh", id="cx-refresh", variant="primary")
                yield Button("Test", id="cx-test")
                yield Button("Pause", id="cx-pause")
                yield Button("Resume", id="cx-resume")
            yield VerticalScroll(Static(id="connectors-body", classes="panel"), classes="body")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        rows = actions.connector_rows(app.ws)
        if not rows:
            body = "[#9a94b0](none registered)[/]"
        else:
            lines = ["[bold #7b6bc4]id · type · health · resources[/]"]
            for r in rows:
                health = r.get("health") or "—"
                tone = (
                    "#2f9d6a" if health in ("healthy", "ok", "active")
                    else "#c9842a" if health not in ("", "—")
                    else "#9a94b0"
                )
                lines.append(
                    f"[#7b6bc4]{r['id']}[/] · {r['type']} · "
                    f"[{tone}]{health}[/]\n"
                    f"  [#9a94b0]{r.get('resources') or '(no resources configured)'}[/]"
                )
            body = "\n".join(lines)
        self.query_one("#connectors-body", Static).update(body)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        cid = self.query_one("#connector-id", Input).value.strip()
        try:
            if event.button.id == "cx-refresh":
                self._refresh()
                return
            if not cid:
                self.notify("enter connector id", severity="warning")
                return
            if event.button.id == "cx-test":
                out = actions.connector_test(app.ws, cid)
                self.notify(f"test {out.get('health', {}).get('status', 'ok')}")
            elif event.button.id == "cx-pause":
                actions.connector_pause(app.ws, cid)
                self.notify(f"paused {cid}")
            elif event.button.id == "cx-resume":
                actions.connector_resume(app.ws, cid)
                self.notify(f"resumed {cid}")
        except Exception as exc:
            self.notify(str(exc), severity="error")
        self._refresh()


class JobsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            yield Label("Jobs", classes="page-title")
            yield Static("Runtime queue — kind · state · progress", classes="page-sub")
            with Horizontal(classes="toolbar"):
                yield Button("cognize_batch", id="enq-cognize", variant="primary")
                yield Button("consolidate_daily", id="enq-consol")
                yield Button("backfill_partition", id="enq-backfill")
                yield Button("Refresh", id="refresh")
            yield VerticalScroll(Static(id="jobs-body", classes="panel"), classes="body")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        snap = actions.jobs_snapshot(app.ws)
        depth = snap.get("depth") or {}
        depth_txt = depth if isinstance(depth, str) else (
            " · ".join(f"{k}={v}" for k, v in depth.items()) if depth else "—"
        )
        lines = [
            f"[bold #7b6bc4]queue depth[/]  [#9a94b0]{depth_txt}[/]",
            "",
            "[bold #7b6bc4]id · kind · state · progress[/]",
        ]
        jobs = snap.get("jobs") or []
        if not jobs:
            lines.append("[#9a94b0](no jobs)[/]")
        for j in jobs:
            state = j.get("state") or "—"
            tone = {
                "pending": "#c9842a",
                "queued": "#c9842a",
                "ready": "#c9842a",
                "running": "#7b6bc4",
                "completed": "#2f9d6a",
                "done": "#2f9d6a",
                "failed": "#c44b5a",
                "dead": "#c44b5a",
            }.get(str(state), "#9a94b0")
            lines.append(
                f"[#7b6bc4]{j.get('id', '')[:14]}[/] · {j.get('kind') or '—'} · "
                f"[{tone}]{state}[/] · {j.get('progress') if j.get('progress') is not None else '—'}\n"
                f"  [#9a94b0]log {j.get('log_ref') or '—'}[/]"
            )
        backfills = snap.get("backfills") or []
        if backfills:
            lines.append("")
            lines.append("[bold #7b6bc4]id · state · progress[/]  [#9a94b0](backfills)[/]")
            for bf in backfills:
                lines.append(
                    f"[#7b6bc4]{bf.get('id', '')}[/] · {bf.get('state') or '—'} · "
                    f"{bf.get('progress') if bf.get('progress') is not None else '—'}"
                )
        self.query_one("#jobs-body", Static).update("\n".join(lines))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        kind_map = {
            "enq-cognize": "cognize_batch",
            "enq-consol": "consolidate_daily",
            "enq-backfill": "backfill_partition",
        }
        bid = event.button.id or ""
        if bid == "refresh":
            self._refresh()
            return
        kind = kind_map.get(bid)
        if not kind:
            return
        try:
            out = actions.enqueue_job(app.ws, kind)
            self.notify(f"enqueued {out['kind']} {out['job_id'][:12]}")
        except Exception as exc:
            self.notify(str(exc), severity="error")
        self._refresh()


def _format_cognize_runs(runs: list[Any]) -> str:
    """Cognize runs as a connectors-style table (id · at · stage · …)."""
    if not runs:
        return "[#9a94b0](no runs yet)[/]"

    lines = ["[bold #7b6bc4]id · at · stage · status · counts[/]"]

    def _status_tone(st: str) -> str:
        return {
            "ok": "#2f9d6a",
            "skipped": "#9a94b0",
            "halted": "#c9842a",
            "error": "#c44b5a",
            "failed": "#c44b5a",
        }.get(st, "#9a94b0")

    for run in runs:
        if not isinstance(run, dict):
            continue
        rid = str(run.get("id") or "")[:18]
        when = str(run.get("created_at") or "—")
        run_status = str(run.get("status") or "—")
        halt = run.get("halt_reason") or ""
        run_detail = (run.get("detail") or "").strip()
        payload = run.get("payload") if isinstance(run.get("payload"), dict) else {}
        stages = (payload.get("stages") if isinstance(payload, dict) else None) or []

        if stages:
            for s in stages:
                if not isinstance(s, dict):
                    continue
                st = str(s.get("status") or "—")
                counts = s.get("counts") or {}
                counts_txt = (
                    " · ".join(f"{k}={v}" for k, v in counts.items())
                    if isinstance(counts, dict) and counts
                    else "—"
                )
                lines.append(
                    f"[#7b6bc4]{rid}[/] · {when} · {s.get('stage') or '—'} · "
                    f"[{_status_tone(st)}]{st}[/] · {counts_txt}"
                )
                sdetail = (s.get("detail") or "").strip()
                if sdetail:
                    lines.append(f"  [#9a94b0]{sdetail[:160]}[/]")
        else:
            lines.append(
                f"[#7b6bc4]{rid}[/] · {when} · — · "
                f"[{_status_tone(run_status)}]{run_status}[/] · —"
            )
            note = " · ".join(p for p in (halt, run_detail[:160]) if p)
            if note:
                lines.append(f"  [#9a94b0]{note}[/]")
    return "\n".join(lines)


class CognizeScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]
    PAGE_SIZE = 5

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._page = 0

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            yield Label("Cognize", classes="page-title")
            yield Static("Pipeline status · open Reflections · run", classes="page-sub")
            with Horizontal(classes="toolbar"):
                yield Button("Refresh", id="cog-refresh")
                yield Button("Run cognize", id="cog-run", variant="primary")
            with Horizontal(classes="toolbar"):
                yield Button("← Prev", id="cog-prev")
                yield Button("Next →", id="cog-next")
                yield Static(id="cog-page-meta", classes="page-sub")
            yield VerticalScroll(Static(id="cognize-body", classes="panel"), classes="body")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        st = actions.cognize_status(app.ws)
        page = actions.cognize_runs_page(
            app.ws, page=self._page, page_size=self.PAGE_SIZE,
        )
        self._page = int(page.get("page") or 0)
        halted = st["halted"]
        halt_mark = (
            f"[bold #c44b5a]halted[/]  {st['halt_reason'] or '—'}"
            if halted
            else "[bold #2f9d6a]ready[/]"
        )
        refs = "\n".join(
            f"  [#7b6bc4]•[/] {r['id'][:10]}  {r['text']}"
            for r in st.get("reflection_previews") or []
        ) or "  [#9a94b0](none)[/]"
        body = (
            f"{halt_mark}\n"
            f"[#9a94b0]detail[/]  {st['detail'] or '—'}\n"
            f"[#9a94b0]open reflections[/]  {st['open_reflections']}\n\n"
            f"[bold #7b6bc4]reflections[/]\n{refs}\n\n"
            f"{_format_cognize_runs(page.get('runs') or [])}"
        )
        self.query_one("#cognize-body", Static).update(body)
        total = int(page.get("total") or 0)
        pages = int(page.get("pages") or 1)
        self.query_one("#cog-page-meta", Static).update(
            f"page {self._page + 1}/{pages}  ·  {total} runs"
        )
        self.query_one("#cog-prev", Button).disabled = not page.get("has_prev")
        self.query_one("#cog-next", Button).disabled = not page.get("has_next")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        bid = event.button.id
        if bid == "cog-refresh":
            self._refresh()
            return
        if bid == "cog-prev":
            if self._page > 0:
                self._page -= 1
            self._refresh()
            return
        if bid == "cog-next":
            self._page += 1
            self._refresh()
            return
        if bid == "cog-run":
            try:
                est = actions.cognize_estimate(app.ws)
            except Exception as exc:
                self.notify(f"estimate failed: {exc}", severity="error")
                return

            def _after_confirm(ok: bool) -> None:
                if not ok:
                    self.notify("cognize cancelled")
                    return
                try:
                    out = actions.enqueue_cognize(app.ws)
                    self.notify(
                        f"queued {out['kind']} {out['job_id'][:12]} — runtime will run it"
                    )
                    if not _alive(app.state.runtime.proc):
                        self.notify(
                            "runtime is stopped — start it on Services",
                            severity="warning",
                        )
                    self._page = 0
                except Exception as exc:
                    self.notify(str(exc), severity="error")
                self._refresh()

            self.app.push_screen(CognizeConfirm(est), _after_confirm)


class ReviewScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            yield Label("Review", classes="page-title")
            yield Static("Human gates · Reflections · accessibility", classes="page-sub")
            yield VerticalScroll(Static(id="review-body", classes="panel"), classes="body")
        yield Footer()

    def on_mount(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        snap = actions.review_snapshot(app.ws)
        url = app.state.serve.url or "http://127.0.0.1:8765"
        refs = "\n".join(
            f"  [#7b6bc4]•[/] {r['id'][:10]}  {r['text']}"
            for r in snap.get("open_reflections") or []
        ) or "  [#9a94b0](none)[/]"
        fade = "\n".join(
            f"  [#7b6bc4]•[/] {r.get('narrative_id', '')[:10]} → "
            f"{r.get('recommended')} ({r.get('reason')})"
            for r in snap.get("accessibility") or []
        ) or "  [#9a94b0](none)[/]"
        backlog = snap["backlog"]
        tone = "#c9842a" if backlog else "#2f9d6a"
        body = (
            f"[bold #7b6bc4]backlog[/]  [{tone}]{backlog}[/] candidates\n"
            f"[bold #7b6bc4]workbench[/]  [#7b6bc4]{url}/#review[/]\n\n"
            f"[bold #7b6bc4]open reflections[/]\n{refs}\n\n"
            f"[bold #7b6bc4]accessibility[/]  [#9a94b0]Fade / Remarkable[/]\n{fade}"
        )
        self.query_one("#review-body", Static).update(body)


class BrowseScreen(Screen):
    """One menu for Cognize entities — Narratives, Stance, Reflections, …"""

    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]
    KINDS = (
        "narratives",
        "stance",
        "reflections",
        "interpretations",
        "situations",
        "relations",
        "traces",
        "percepts",
    )

    def __init__(self, kind: str = "narratives", **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self._kind = kind if kind in self.KINDS else "narratives"

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            yield Label("Browse", classes="page-title")
            yield Static(
                "Cognize entities — pick a submenu",
                classes="page-sub",
            )
            with Horizontal(classes="toolbar"):
                for k in self.KINDS:
                    yield Button(
                        k.capitalize(),
                        id=f"br-{k}",
                        variant="primary" if k == self._kind else "default",
                    )
            with Horizontal(classes="toolbar"):
                yield Button("Refresh", id="br-refresh")
                yield Input(placeholder="proposal id (stance)", id="proposal-id")
                yield Button("Approve proposal", id="br-approve")
            yield VerticalScroll(Static(id="browse-body", classes="panel"), classes="body")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _set_kind(self, kind: str) -> None:
        if kind not in self.KINDS:
            return
        self._kind = kind
        for k in self.KINDS:
            btn = self.query_one(f"#br-{k}", Button)
            btn.variant = "primary" if k == kind else "default"
        self._refresh()

    def _format_body(self) -> str:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        kind = self._kind
        header = f"[bold #7b6bc4]{kind}[/]"

        if kind == "narratives":
            rows = actions.narrative_list(app.ws)
            if not rows:
                return f"{header}\n[#9a94b0](none)[/]"
            lines = [header, "[bold #7b6bc4]id · status/epistemic · grain · account[/]"]
            for n in rows:
                lines.append(
                    f"[#7b6bc4]{n['id'][:12]}[/] · {n['status']}/{n['epistemic']} · "
                    f"{n['grain'] or '—'} · {(n['account'] or '')[:70]}"
                )
            return "\n".join(lines)

        if kind == "stance":
            ov = actions.stance_overview(app.ws)
            stances = ov.get("stances") or []
            proposals = ov.get("proposals") or []
            s_lines = [
                f"[#7b6bc4]{s['id'][:12]}[/] · {s['status']} · {(s['statement'] or '')[:70]}"
                for s in stances
            ] or ["[#9a94b0](no active stances)[/]"]
            p_lines = [
                f"[#c9842a]{p['id'][:12]}[/] · nar={p.get('narrative_id') or '—'} · "
                f"{(p.get('reason') or '')[:50]}"
                for p in proposals
            ] or ["[#9a94b0](none)[/]"]
            return (
                f"{header}\n[bold #7b6bc4]id · status · statement[/]\n"
                + "\n".join(s_lines)
                + "\n\n[bold #7b6bc4]pending proposals[/]\n"
                + "\n".join(p_lines)
            )

        if kind == "reflections":
            rows = actions.reflection_list(app.ws)
            if not rows:
                return f"{header}\n[#9a94b0](none)[/]"
            lines = [header, "[bold #7b6bc4]id · status · text[/]"]
            for r in rows:
                lines.append(
                    f"[#7b6bc4]{r['id'][:12]}[/] · {r['status']} · {r['text']}"
                )
            return "\n".join(lines)

        if kind == "interpretations":
            rows = actions.interpretation_list(app.ws)
            if not rows:
                return f"{header}\n[#9a94b0](none)[/]"
            lines = [header, "[bold #7b6bc4]id · status · explanation[/]"]
            for r in rows:
                lines.append(
                    f"[#7b6bc4]{str(r['id'])[:12]}[/] · {r['status']} · {r['explanation']}"
                )
            return "\n".join(lines)

        if kind == "situations":
            rows = actions.situation_list(app.ws)
            if not rows:
                return f"{header}\n[#9a94b0](none)[/]"
            lines = [header, "[bold #7b6bc4]id · status · domain · percepts · summary[/]"]
            for r in rows:
                lines.append(
                    f"[#7b6bc4]{r['id'][:12]}[/] · {r['status']} · {r['domain'] or '—'} · "
                    f"{r['percepts']} · {r['summary']}"
                )
            return "\n".join(lines)

        if kind == "relations":
            rows = actions.relation_list(app.ws)
            if not rows:
                return f"{header}\n[#9a94b0](none)[/]"
            lines = [header, "[bold #7b6bc4]id · type · from · to[/]"]
            for r in rows:
                lines.append(
                    f"[#7b6bc4]{r['id'][:12]}[/] · {r['type']} · "
                    f"{str(r['from_id'])[:10]} → {str(r['to_id'])[:10]}"
                )
                if r.get("rationale"):
                    lines.append(f"  [#9a94b0]{r['rationale']}[/]")
            return "\n".join(lines)

        if kind == "traces":
            rows = actions.trace_list(app.ws)
            if not rows:
                return f"{header}\n[#9a94b0](none)[/]"
            lines = [header, "[bold #7b6bc4]id · event · resource · at[/]"]
            for r in rows:
                lines.append(
                    f"[#7b6bc4]{r['id'][:12]}[/] · {r['event_kind'] or '—'} · "
                    f"{r.get('resource_kind') or '—'} {str(r['resource_id'] or '—')[:12]} · "
                    f"{str(r.get('created_at') or '—')[:19]}"
                )
                if r.get("summary"):
                    lines.append(f"  [#9a94b0]{r['summary']}[/]")
            return "\n".join(lines)

        # percepts
        rows = actions.percept_list(app.ws)
        if not rows:
            return f"{header}\n[#9a94b0](none)[/]"
        lines = [header, "[bold #7b6bc4]id · sensor · at · content[/]"]
        for r in rows:
            lines.append(
                f"[#7b6bc4]{r['id'][:12]}[/] · {r['sensor'] or '—'} · "
                f"{str(r['ingested_at'] or '—')[:19]} · {r['content']}"
            )
        return "\n".join(lines)

    def _refresh(self) -> None:
        self.query_one("#browse-body", Static).update(self._format_body())

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        bid = event.button.id or ""
        if bid == "br-refresh":
            self._refresh()
            return
        if bid.startswith("br-") and bid[3:] in self.KINDS:
            self._set_kind(bid[3:])
            return
        if bid == "br-approve":
            if self._kind != "stance":
                self.notify("switch to Stance to approve proposals", severity="warning")
                return
            pid = self.query_one("#proposal-id", Input).value.strip()
            if not pid:
                self.notify("enter proposal id", severity="warning")
                return
            try:
                actions.approve_stance_proposal(app.ws, pid)
                self.notify(f"approved {pid}")
            except Exception as exc:
                self.notify(str(exc), severity="error")
            self._refresh()


class McpScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            yield Label("MCP", classes="page-title")
            yield Static("Host tool surface · process identity", classes="page-sub")
            yield Static(id="mcp-body", classes="panel")
        yield Footer()

    def on_mount(self) -> None:
        body = (
            "[bold #7b6bc4]identity[/]\n"
            "  TWIN_MCP_CLIENT + TWIN_MCP_CLIENT_TOKEN\n"
            "  setup: [#7b6bc4]twin setup mcp <client>[/]\n\n"
            "[bold #7b6bc4]prefer[/]\n"
            "  inject_context_pack\n"
            "  narrative_list / narrative_show\n"
            "  stance_list / stance_proposals / stance_profile\n"
            "  claim_search / claim_get\n"
        )
        self.query_one("#mcp-body", Static).update(body)


class PaletteScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(classes="page"):
            yield Label("Palette", classes="page-title")
            yield Static("Fuzzy Cognize / Narrative / Stance / Inject verbs", classes="page-sub")
            yield Input(placeholder="type to filter…", id="palette-input")
            yield ListView(id="palette-list")
        yield Footer()

    def on_mount(self) -> None:
        self.query_one("#palette-input", Input).focus()
        self._fill("")

    def _fill(self, query: str) -> None:
        lv = self.query_one("#palette-list", ListView)
        lv.clear()
        for item in fuzzy_palette(query):
            lv.append(ListItem(Label(f"  {item}")))

    def on_input_changed(self, event: Input.Changed) -> None:
        self._fill(event.value)


class TwinCenterApp(App[None]):
    TITLE = "twin"
    SUB_TITLE = "Command Center"
    CSS = _TWIN_CSS
    # Prefer `/` PaletteScreen — disable Textual's built-in ctrl+p command palette.
    ENABLE_COMMAND_PALETTE = False

    def __init__(self, ws: Workspace, state: CenterState, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        self.ws = ws
        self.state = state

    def on_mount(self) -> None:
        self.push_screen(HomeScreen())

    def action_quit_center(self) -> None:
        def done(choice: Optional[str]) -> None:
            if choice in ("stop", "leave"):
                self.state.exit_choice = choice or "leave"
                self.exit()

        self.push_screen(ExitPrompt(), done)
