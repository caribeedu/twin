"""Textual Command Center application."""

from __future__ import annotations

from typing import Any, Optional

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, ListItem, ListView, Static

from twin.interfaces.center import (
    CenterState,
    fuzzy_palette,
    home_snapshot,
    start_runtime,
    start_serve,
    stop_runtime,
    stop_serve,
)
from twin.workspace import Workspace


class ExitPrompt(ModalScreen[str]):
    """Stop supervised services? Yes / Leave running / Cancel."""

    def compose(self) -> ComposeResult:
        yield Vertical(
            Label("Stop supervised services?"),
            Horizontal(
                Button("Yes — stop", id="stop", variant="error"),
                Button("Leave running", id="leave", variant="primary"),
                Button("Cancel", id="cancel"),
            ),
            id="exit-dialog",
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        self.dismiss(event.button.id or "cancel")


class HomeScreen(Screen):
    BINDINGS = [
        Binding("s", "goto_services", "Services"),
        Binding("c", "goto_connectors", "Connectors"),
        Binding("j", "goto_jobs", "Jobs"),
        Binding("g", "goto_cognize", "Cognize"),
        Binding("r", "goto_review", "Review"),
        Binding("n", "goto_narratives", "Narratives"),
        Binding("t", "goto_stance", "Stance"),
        Binding("m", "goto_mcp", "MCP"),
        Binding("slash", "palette", "Palette"),
        Binding("q", "quit_center", "Quit"),
    ]

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield VerticalScroll(Static(id="home-body"))
        yield Footer()

    def on_mount(self) -> None:
        self.refresh_home()

    def refresh_home(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        snap = home_snapshot(app.ws)
        serve = "running" if app.state.serve.proc and app.state.serve.proc.poll() is None else "stopped"
        runtime = "running" if app.state.runtime.proc and app.state.runtime.proc.poll() is None else "stopped"
        body = (
            f"[b]Twin Command Center[/b]\n\n"
            f"home: {snap['home']}\n"
            f"review backlog: {snap['review_backlog']}\n"
            f"open reflections: {snap['open_reflections']}\n"
            f"connectors: {snap['connectors']}\n"
            f"jobs pending: {snap['jobs_pending']}\n"
            f"cognize halt: {snap['cognize_halt'] or '(none)'}\n"
            f"serve: {serve} {app.state.serve.url}\n"
            f"runtime: {runtime}\n\n"
            f"Keys: s services · c connectors · j jobs · g cognize · "
            f"r review · n narratives · t stance · m mcp · / palette · q quit"
        )
        self.query_one("#home-body", Static).update(body)

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

    def action_goto_narratives(self) -> None:
        self.app.push_screen(NarrativesScreen())

    def action_goto_stance(self) -> None:
        self.app.push_screen(StanceScreen())

    def action_goto_mcp(self) -> None:
        self.app.push_screen(McpScreen())

    def action_palette(self) -> None:
        self.app.push_screen(PaletteScreen())

    def action_quit_center(self) -> None:
        self.app.action_quit_center()


class ServicesScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back"), Binding("q", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Label("Services — supervised serve / runtime"),
            Horizontal(
                Button("Start serve", id="start-serve"),
                Button("Stop serve", id="stop-serve"),
                Button("Start runtime", id="start-runtime"),
                Button("Stop runtime", id="stop-runtime"),
            ),
            Static(id="services-status"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        serve_alive = app.state.serve.proc and app.state.serve.proc.poll() is None
        rt_alive = app.state.runtime.proc and app.state.runtime.proc.poll() is None
        self.query_one("#services-status", Static).update(
            f"serve: {'RUNNING ' + app.state.serve.url if serve_alive else 'stopped'}\n"
            f"runtime: {'RUNNING (attached)' if rt_alive else 'stopped'}\n"
            f"logs: {app.state.serve.log_path or '-'} · {app.state.runtime.log_path or '-'}"
        )

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        bid = event.button.id
        if bid == "start-serve":
            url = start_serve(app.state)
            self.notify(f"serve at {url}")
        elif bid == "stop-serve":
            stop_serve(app.state)
        elif bid == "start-runtime":
            msg = start_runtime(app.state)
            self.notify(f"runtime {msg}")
        elif bid == "stop-runtime":
            stop_runtime(app.state)
        self._refresh()


class ConnectorsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Static(id="connectors-body"))
        yield Footer()

    def on_mount(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        rows = []
        if hasattr(app.ws.store, "list_connector_instances"):
            for inst in app.ws.store.list_connector_instances():
                rows.append(
                    f"{getattr(inst, 'id', '?')} · {getattr(inst, 'connector_type', getattr(inst, 'type', '?'))} · "
                    f"{getattr(inst, 'status', '')}"
                )
        body = "Connectors (Sense I/O)\n\n" + ("\n".join(rows) if rows else "(none registered)")
        body += "\n\nDestructive revoke still requires CLI confirm (`twin connector …`)."
        self.query_one("#connectors-body", Static).update(body)


class JobsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Label("Jobs — same runtime queue as CLI"),
            Horizontal(
                Button("Enqueue cognize", id="enq-cognize"),
                Button("Enqueue consolidate daily", id="enq-consol"),
                Button("Refresh", id="refresh"),
            ),
            Static(id="jobs-body"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        lines = []
        if hasattr(app.ws.store, "runtime_queue_depth"):
            lines.append(f"depth: {app.ws.store.runtime_queue_depth()}")
        if hasattr(app.ws.store, "list_runtime_jobs"):
            try:
                for job in app.ws.store.list_runtime_jobs(limit=15):
                    lines.append(
                        f"{getattr(job, 'id', '?')[:12]} {getattr(job, 'kind', '')} "
                        f"{getattr(job, 'status', getattr(job, 'state', ''))}"
                    )
            except Exception as exc:
                lines.append(f"(list error: {exc})")
        self.query_one("#jobs-body", Static).update("\n".join(lines) or "(no jobs)")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        try:
            from twin.runtime.queue import RuntimeQueue
            from twin.runtime.models import JobKind

            q = RuntimeQueue(app.ws.store)
            if event.button.id in ("enq-cognize", "enq-consol"):
                q.enqueue(JobKind.consolidate_daily, payload={}, vault_id="default")
                self.notify("enqueued consolidate_daily")
        except Exception as exc:
            self.notify(str(exc), severity="error")
        self._refresh()


class CognizeScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Static(id="cognize-body"))
        yield Footer()

    def on_mount(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        from twin.cognize.gate import require_chat_llm
        import os

        gate = require_chat_llm(
            extractor=app.ws.cfg.extractor,
            chat_provider=app.ws.cfg.normalized_llm_provider,
            allow_echo_cognition=os.environ.get("TWIN_ALLOW_ECHO_COGNITION", "") == "1",
        )
        last = ""
        if hasattr(app.ws.store, "last_cognize_run"):
            last = str(app.ws.store.last_cognize_run() or "")
        refs = 0
        if hasattr(app.ws.store, "list_open_reflections"):
            refs = len(app.ws.store.list_open_reflections("default"))
        body = (
            "Cognize\n\n"
            f"halted: {gate.halted}\n"
            f"halt_reason: {gate.halt_reason.value if gate.halt_reason else '(none)'}\n"
            f"detail: {gate.detail}\n"
            f"open reflections: {refs}\n"
            f"last run: {last[:200]}\n\n"
            "Run via CLI: twin cognize run"
        )
        self.query_one("#cognize-body", Static).update(body)


class ReviewScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Static(id="review-body"))
        yield Footer()

    def on_mount(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        snap = home_snapshot(app.ws)
        url = app.state.serve.url or "http://127.0.0.1:8765"
        refs = []
        if hasattr(app.ws.store, "list_open_reflections"):
            for r in app.ws.store.list_open_reflections("default")[:8]:
                refs.append(f"- {r.id[:10]} {r.text[:60]}")
        body = (
            "Review\n\n"
            f"candidate backlog: {snap['review_backlog']}\n"
            f"workbench: {url}/review\n\n"
            "Open Reflections:\n"
            + ("\n".join(refs) if refs else "(none)")
            + "\n\nCLI: twin review · twin serve"
        )
        self.query_one("#review-body", Static).update(body)


class NarrativesScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Static(id="narratives-body"))
        yield Footer()

    def on_mount(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        lines = []
        if hasattr(app.ws.store, "list_narratives"):
            for nar in app.ws.store.list_narratives("default")[:20]:
                st = nar.status.value if hasattr(nar.status, "value") else nar.status
                lines.append(f"{nar.id[:12]} [{st}] {(nar.account or '')[:70]}")
        self.query_one("#narratives-body", Static).update(
            "Narratives\n\n" + ("\n".join(lines) if lines else "(none)")
        )


class StanceScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Static(id="stance-body"))
        yield Footer()

    def on_mount(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        from twin.cognize.stance import list_stances

        lines = [f"{s.id[:12]} {(s.statement or '')[:70]}" for s in list_stances(app.ws.store)[:20]]
        pending = []
        if hasattr(app.ws.store, "list_judgment_proposals"):
            for p in app.ws.store.list_judgment_proposals(status="pending", limit=10):
                pending.append(f"proposal {p.id[:12]} {(p.reason or '')[:50]}")
        body = (
            "Stance\n\n"
            + ("\n".join(lines) if lines else "(no active stances)")
            + "\n\nPending proposals:\n"
            + ("\n".join(pending) if pending else "(none)")
        )
        self.query_one("#stance-body", Static).update(body)


class McpScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Static(id="mcp-body"))
        yield Footer()

    def on_mount(self) -> None:
        body = (
            "MCP\n\n"
            "Process identity: TWIN_MCP_CLIENT + TWIN_MCP_CLIENT_TOKEN\n"
            "Setup: twin setup mcp <client>\n"
            "Preferred pack tool: inject_context_pack\n"
            "Legacy: memory_safe_context_pack (deprecated)\n"
        )
        self.query_one("#mcp-body", Static).update(body)


class PaletteScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="fuzzy v2 verbs…", id="palette-input")
        yield ListView(id="palette-list")
        yield Footer()

    def on_mount(self) -> None:
        self._fill("")

    def _fill(self, query: str) -> None:
        lv = self.query_one("#palette-list", ListView)
        lv.clear()
        for item in fuzzy_palette(query):
            lv.append(ListItem(Label(item)))

    def on_input_changed(self, event: Input.Changed) -> None:
        self._fill(event.value)


class TwinCenterApp(App[None]):
    TITLE = "Twin Command Center"
    CSS = """
    #exit-dialog { padding: 1 2; border: solid $accent; width: 60; height: auto; }
    Screen { background: $surface; }
    """

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
            # cancel → stay

        self.push_screen(ExitPrompt(), done)
