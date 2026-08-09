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
from twin.interfaces.center import actions
from twin.workspace import Workspace


class ExitPrompt(ModalScreen[str]):
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
        doc = actions.doctor_summary(app.ws)
        serve = "running" if app.state.serve.proc and app.state.serve.proc.poll() is None else "stopped"
        runtime = "running" if app.state.runtime.proc and app.state.runtime.proc.poll() is None else "stopped"
        warns = "\n".join(
            f"  · {w.get('name')}: {w.get('detail')}" for w in (doc.get("warnings") or [])[:5]
        ) or "  (none)"
        body = (
            f"[b]Twin Command Center[/b]\n\n"
            f"home: {snap['home']}\n"
            f"doctor: {doc.get('checks_ok')}/{doc.get('checks_total')} ok · "
            f"llm={doc.get('llm')} extractor={doc.get('extractor')}\n"
            f"warnings:\n{warns}\n"
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
            self.notify(f"serve at {start_serve(app.state)}")
        elif bid == "stop-serve":
            stop_serve(app.state)
        elif bid == "start-runtime":
            self.notify(f"runtime {start_runtime(app.state)}")
        elif bid == "stop-runtime":
            stop_runtime(app.state)
        self._refresh()


class ConnectorsScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Label("Connectors (Sense I/O) — pause / resume / test"),
            Input(placeholder="connector id", id="connector-id"),
            Horizontal(
                Button("Refresh", id="cx-refresh"),
                Button("Test", id="cx-test"),
                Button("Pause", id="cx-pause"),
                Button("Resume", id="cx-resume"),
            ),
            Static(id="connectors-body"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        rows = actions.connector_rows(app.ws)
        lines = [
            f"{r['id']} · {r['type']} · status={r['status']} · health={r['health']}"
            for r in rows
        ]
        body = "\n".join(lines) if lines else "(none registered)"
        body += "\n\nRevoke remains CLI-confirmed: twin connector revoke <id>"
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
        yield Header()
        yield Vertical(
            Label("Jobs — runtime queue (kind · state · progress · log_ref)"),
            Horizontal(
                Button("Enqueue cognize_batch", id="enq-cognize"),
                Button("Enqueue consolidate_daily", id="enq-consol"),
                Button("Enqueue backfill_partition", id="enq-backfill"),
                Button("Refresh", id="refresh"),
            ),
            Static(id="jobs-body"),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        snap = actions.jobs_snapshot(app.ws)
        lines = [f"depth: {snap.get('depth')}"]
        for j in snap.get("jobs") or []:
            lines.append(
                f"{j.get('id', '')[:12]} · {j.get('kind')} · {j.get('state')} · "
                f"progress={j.get('progress')} · log={j.get('log_ref') or '-'}"
            )
        if snap.get("backfills"):
            lines.append("\nBackfills:")
            for bf in snap["backfills"]:
                lines.append(f"  {bf.get('id')} · {bf.get('state')} · {bf.get('progress')}")
        self.query_one("#jobs-body", Static).update("\n".join(lines) or "(no jobs)")

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


class CognizeScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Horizontal(
                Button("Refresh", id="cog-refresh"),
                Button("Run cognize", id="cog-run"),
            ),
            VerticalScroll(Static(id="cognize-body")),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        st = actions.cognize_status(app.ws)
        refs = "\n".join(
            f"- {r['id'][:10]} {r['text']}" for r in st.get("reflection_previews") or []
        ) or "(none)"
        body = (
            "Cognize\n\n"
            f"halted: {st['halted']}\n"
            f"halt_reason: {st['halt_reason'] or '(none)'}\n"
            f"detail: {st['detail']}\n"
            f"open reflections: {st['open_reflections']}\n"
            f"{refs}\n"
            f"last run: {str(st.get('last_run') or '')[:240]}"
        )
        self.query_one("#cognize-body", Static).update(body)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        if event.button.id == "cog-refresh":
            self._refresh()
            return
        if event.button.id == "cog-run":
            try:
                out = actions.cognize_run(app.ws)
                self.notify(f"cognize status={out.get('status') or out.get('ok')}")
            except Exception as exc:
                self.notify(str(exc), severity="error")
            self._refresh()


class ReviewScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield VerticalScroll(Static(id="review-body"))
        yield Footer()

    def on_mount(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        snap = actions.review_snapshot(app.ws)
        url = app.state.serve.url or "http://127.0.0.1:8765"
        refs = "\n".join(
            f"- {r['id'][:10]} {r['text']}" for r in snap.get("open_reflections") or []
        ) or "(none)"
        fade = "\n".join(
            f"- {r.get('narrative_id', '')[:10]} → {r.get('recommended')} ({r.get('reason')})"
            for r in snap.get("accessibility") or []
        ) or "(none)"
        body = (
            "Review\n\n"
            f"candidate backlog: {snap['backlog']}\n"
            f"workbench: {url}/#review\n\n"
            "Open Reflections:\n"
            f"{refs}\n\n"
            "Accessibility (Fade/Remarkable):\n"
            f"{fade}"
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
        for n in actions.narrative_list(app.ws):
            lines.append(
                f"{n['id'][:12]} [{n['status']}/{n['epistemic']}] "
                f"grain={n['grain'] or '-'} {(n['account'] or '')[:70]}"
            )
        self.query_one("#narratives-body", Static).update(
            "Narratives\n\n" + ("\n".join(lines) if lines else "(none)")
        )


class StanceScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Input(placeholder="proposal id to approve", id="proposal-id"),
            Horizontal(
                Button("Refresh", id="st-refresh"),
                Button("Approve proposal", id="st-approve"),
            ),
            VerticalScroll(Static(id="stance-body")),
        )
        yield Footer()

    def on_mount(self) -> None:
        self._refresh()

    def _refresh(self) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        ov = actions.stance_overview(app.ws)
        lines = [
            f"{s['id'][:12]} [{s['status']}] {(s['statement'] or '')[:70]}"
            for s in ov.get("stances") or []
        ]
        pending = [
            f"proposal {p['id'][:12]} nar={p.get('narrative_id') or '-'} {(p.get('reason') or '')[:50]}"
            for p in ov.get("proposals") or []
        ]
        body = (
            "Stance\n\n"
            + ("\n".join(lines) if lines else "(no active stances)")
            + "\n\nPending proposals:\n"
            + ("\n".join(pending) if pending else "(none)")
        )
        self.query_one("#stance-body", Static).update(body)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        app: TwinCenterApp = self.app  # type: ignore[assignment]
        if event.button.id == "st-refresh":
            self._refresh()
            return
        if event.button.id == "st-approve":
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
        yield Header()
        yield VerticalScroll(Static(id="mcp-body"))
        yield Footer()

    def on_mount(self) -> None:
        body = (
            "MCP\n\n"
            "Process identity: TWIN_MCP_CLIENT + TWIN_MCP_CLIENT_TOKEN\n"
            "Setup: twin setup mcp <client>\n"
            "Pack: inject_context_pack\n"
            "Narratives: narrative_list / narrative_show\n"
            "Stance: stance_list / stance_proposals\n"
        )
        self.query_one("#mcp-body", Static).update(body)


class PaletteScreen(Screen):
    BINDINGS = [Binding("escape", "app.pop_screen", "Back")]

    def compose(self) -> ComposeResult:
        yield Header()
        yield Input(placeholder="fuzzy verbs…", id="palette-input")
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

        self.push_screen(ExitPrompt(), done)
