"""CLI developer experience helpers.

Rules, panels, legends, tables, single-key input, progress with ETA, and Twin
brand styling. Uses ``rich`` when installed; falls back to plain stdout so
CI/tests never hard-depend on it.
"""

from __future__ import annotations

import os
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Iterator, Sequence


# Twin brand — purple accents. Avoid "dim magenta": near-invisible on
# Ubuntu's default terminal palette (poor contrast for secondary text).
BRAND = "magenta"
BRAND_BOLD = "bold magenta"
BRAND_BORDER = "bright_magenta"
OK = "green"
WARN = "yellow"
ERR = "red"


def _rich():
    try:
        from rich.console import Console
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
            TimeRemainingColumn,
        )
        from rich.panel import Panel
        from rich.text import Text
        from rich.table import Table
        return {
            "Console": Console,
            "Progress": Progress,
            "SpinnerColumn": SpinnerColumn,
            "BarColumn": BarColumn,
            "TextColumn": TextColumn,
            "MofNCompleteColumn": MofNCompleteColumn,
            "TimeElapsedColumn": TimeElapsedColumn,
            "TimeRemainingColumn": TimeRemainingColumn,
            "Panel": Panel,
            "Text": Text,
            "Table": Table,
        }
    except Exception:
        return None


def console():
    r = _rich()
    if r:
        return r["Console"](highlight=False)
    return None


def print_rule(title: str = "") -> None:
    c = console()
    if c is not None:
        c.rule(f"[{BRAND_BOLD}]{title}[/]" if title else "")
        return
    line = "─" * 56
    print(f"{line} {title}" if title else line)


def print_panel(body: str, *, title: str = "", style: str = BRAND_BORDER) -> None:
    r = _rich()
    if r:
        titled = f"[{BRAND_BOLD}]{title}[/]" if title else None
        r["Console"]().print(
            r["Panel"](body, title=titled, border_style=style, style="white"),
        )
        return
    if title:
        print(f"┌─ {title}")
    for line in body.splitlines() or [body]:
        print(f"│ {line}")
    print("└" + "─" * 40)


def print_legend(entries: Sequence[tuple[str, str]], *, title: str = "keys") -> None:
    """Show a key→action legend (review / interactive flows)."""
    r = _rich()
    if r:
        table = r["Table"](show_header=False, box=None, padding=(0, 2))
        table.add_column("key", style=BRAND_BOLD, width=5)
        table.add_column("action", style="white")
        for key, action in entries:
            table.add_row(key, action)
        r["Console"]().print(
            r["Panel"](table, title=f"[{BRAND_BOLD}]{title}[/]", border_style=BRAND_BORDER),
        )
        return
    print(f"┌─ {title}")
    for key, action in entries:
        print(f"│  {key}  {action}")
    print("└" + "─" * 40)


def print_ok(msg: str) -> None:
    c = console()
    if c is not None:
        c.print(f"[{OK}]✓[/] {msg}")
    else:
        print(f"✓ {msg}")


def print_warn(msg: str) -> None:
    c = console()
    if c is not None:
        c.print(f"[{WARN}]![/] {msg}")
    else:
        print(f"! {msg}")


def print_err(msg: str) -> None:
    c = console()
    if c is not None:
        c.print(f"[{ERR}]✗[/] {msg}")
    else:
        print(f"✗ {msg}")


def print_dim(msg: str) -> None:
    c = console()
    if c is not None:
        c.print(msg)
    else:
        print(msg)


def print_kv(rows: Sequence[tuple[str, str]]) -> None:
    """Key/value meta strip (search/pack headers)."""
    r = _rich()
    if r:
        table = r["Table"](show_header=False, box=None, padding=(0, 1))
        # Keys: bright magenta (readable); values: white
        table.add_column("k", style="bold bright_magenta")
        table.add_column("v", style="bright_white")
        for k, v in rows:
            table.add_row(k, v)
        r["Console"]().print(table)
        return
    for k, v in rows:
        print(f"  {k}: {v}")


def print_table(
    headers: Sequence[str],
    rows: Sequence[Sequence[object]],
    *,
    title: str = "",
) -> None:
    """Render a branded table; plain aligned columns without Rich.

    Empty ``rows`` prints nothing (callers show their own empty-state warning).
    """
    if not rows:
        return
    str_rows = [[("" if c is None else str(c)) for c in row] for row in rows]
    r = _rich()
    if r:
        table = r["Table"](
            show_header=True,
            header_style=BRAND_BOLD,
            box=None,
            padding=(0, 2),
            title=(f"[{BRAND_BOLD}]{title}[/]" if title else None),
        )
        for head in headers:
            table.add_column(str(head), style="bright_white", overflow="fold")
        for row in str_rows:
            table.add_row(*row)
        r["Console"](highlight=False).print(table)
        return
    widths = [len(str(h)) for h in headers]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    if title:
        print(title)
    print("  ".join(str(h).ljust(widths[i]) for i, h in enumerate(headers)))
    print("  ".join("-" * widths[i] for i in range(len(headers))))
    for row in str_rows:
        print("  ".join(cell.ljust(widths[i]) for i, cell in enumerate(row)))


def print_next(entries: Sequence[tuple[str, str]]) -> None:
    """Show a "next steps" legend (arrow + suggested command)."""
    print_legend(entries, title="next")


def score_bar(score: float, *, width: int = 12) -> str:
    """ASCII score bar 0..1 for plain terminals; Rich markup when available."""
    score = max(0.0, min(1.0, float(score)))
    filled = int(round(score * width))
    bar = "█" * filled + "░" * (width - filled)
    return f"{bar} {score:.3f}"


def read_key(
    prompt: str = "",
    *,
    allowed: str = "",
    accept_enter: bool = False,
) -> str:
    """Read a single character without requiring Enter (TTY).

    Falls back to ``input()`` when stdin is not a TTY (pipes/CI).
    When ``accept_enter`` is True, Enter returns ``""`` (useful for Y/n defaults).
    """
    if prompt:
        sys.stdout.write(prompt)
        sys.stdout.flush()
    if not sys.stdin.isatty():
        line = input().strip()
        return (line[:1] if line else "").lower()

    # Windows
    try:
        import msvcrt  # type: ignore

        while True:
            ch = msvcrt.getwch()
            if ch in ("\r", "\n"):
                if accept_enter:
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return ""
                continue
            if ch == "\x03":
                raise KeyboardInterrupt
            key = ch.lower()
            if not allowed or key in allowed:
                sys.stdout.write(key + "\n")
                sys.stdout.flush()
                return key
    except ImportError:
        pass

    # POSIX
    import termios
    import tty

    fd = sys.stdin.fileno()
    old = termios.tcgetattr(fd)
    try:
        tty.setraw(fd)
        while True:
            ch = sys.stdin.read(1)
            if ch in ("\r", "\n"):
                if accept_enter:
                    termios.tcsetattr(fd, termios.TCSADRAIN, old)
                    sys.stdout.write("\n")
                    sys.stdout.flush()
                    return ""
                continue
            if ch == "\x03":
                raise KeyboardInterrupt
            key = ch.lower()
            if not allowed or key in allowed:
                # restore before echo so newline behaves
                termios.tcsetattr(fd, termios.TCSADRAIN, old)
                sys.stdout.write(key + "\n")
                sys.stdout.flush()
                return key
    finally:
        termios.tcsetattr(fd, termios.TCSADRAIN, old)


def prompt_line(prompt: str, *, default: str = "") -> str:
    suffix = f" [{default}]" if default else ""
    c = console()
    if c is not None:
        value = c.input(f"[{BRAND_BOLD}]{prompt}[/]{suffix}: ").strip()
    else:
        value = input(f"{prompt}{suffix}: ").strip()
    return value or default


def prompt_yes_no(prompt: str, *, default: bool = True) -> bool:
    hint = "Y/n" if default else "y/N"
    while True:
        key = read_key(f"{prompt} ({hint}) ", allowed="yn", accept_enter=True)
        if key == "y":
            return True
        if key == "n":
            return False
        if not key:
            return default


@dataclass
class _PlainProgress:
    total: int
    desc: str
    done: int = 0
    started: float = 0.0

    def __post_init__(self) -> None:
        self.started = time.monotonic()

    def advance(self, label: str = "") -> None:
        self.done += 1
        elapsed = max(0.001, time.monotonic() - self.started)
        rate = self.done / elapsed
        remain = (self.total - self.done) / rate if rate > 0 else 0
        eta = _fmt_secs(remain)
        pct = int(100 * self.done / max(self.total, 1))
        msg = f"[{self.done}/{self.total} {pct}%] eta {eta}  {label}"
        print(msg)


def _fmt_secs(seconds: float) -> str:
    seconds = max(0, int(seconds))
    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h:d}h{m:02d}m"
    if m:
        return f"{m:d}m{s:02d}s"
    return f"{s:d}s"


@contextmanager
def progress_bar(total: int, *, description: str = "Working") -> Iterator:
    """Yield ``advance(label='')`` callback. Shows ETA when possible."""
    r = _rich()
    if r is None or total <= 0 or not sys.stdout.isatty():
        plain = _PlainProgress(total=max(total, 0), desc=description)
        if total <= 0:
            yield (lambda label="": None)
            return

        def advance(label: str = "") -> None:
            plain.advance(label)

        print(f"{description} ({total} item(s))…")
        yield advance
        return

    Progress = r["Progress"]
    with Progress(
        r["SpinnerColumn"](style=BRAND),
        r["TextColumn"](f"[bold {BRAND}]{{task.description}}"),
        r["BarColumn"](complete_style=BRAND, finished_style=BRAND_BOLD),
        r["MofNCompleteColumn"](),
        r["TimeElapsedColumn"](),
        r["TimeRemainingColumn"](),
        console=r["Console"](),
        transient=False,
    ) as progress:
        task_id = progress.add_task(description, total=total)

        def advance(label: str = "") -> None:
            if label:
                progress.update(task_id, description=f"{description} · {label}")
            progress.advance(task_id, 1)

        yield advance


def _current_backfill_partition(progress: dict) -> str:
    for part in progress.get("partitions") or []:
        status = part.get("status")
        if status in ("running", "continuation_pending", "planned", "failed"):
            return str(part.get("partition_key") or "")
    return ""


def watch_backfill_job(
    store,
    job_id: str,
    *,
    poll_seconds: float = 0.5,
    stall_warn_seconds: float = 8.0,
    stop_check=None,
) -> dict:
    """Poll a BackfillJob until terminal; show progress bar + ETA (watch only).

    Does not execute partitions — the cognitive runtime must drain
    ``backfill_partition`` jobs. Warns if progress stalls (runtime likely down).
    """
    job = store.get_backfill_job(job_id)
    if job is None:
        raise ValueError(f"backfill job {job_id} not found")
    progress = job.progress or {}
    total = int(progress.get("total_partitions") or 0)
    completed = int(progress.get("completed_partitions") or 0)
    terminal = {"completed", "failed", "cancelled"}
    status = job.status.value if hasattr(job.status, "value") else str(job.status)
    if status in terminal:
        print_kv([
            ("job", job_id),
            ("status", status),
            ("partitions", f"{completed}/{total}"),
        ])
        return {
            "job_id": job_id,
            "status": status,
            "completed_partitions": completed,
            "total_partitions": total,
            "done": True,
        }

    print_rule("backfill · run")
    print_kv([
        ("job", job_id),
        ("connector", job.connector_id),
        ("partitions", f"{completed}/{total}"),
    ])
    print_dim("watching runtime · partitions execute via twin runtime start")

    warned_stall = False
    started = time.monotonic()
    last_completed = completed
    last_version = int(getattr(job, "version", 0) or 0)
    last_progress_at = started
    bar_total = max(total, 1)
    stalled_exit = False

    with progress_bar(bar_total, description="Backfill") as advance:
        for _ in range(min(completed, bar_total)):
            advance()
        while True:
            if stop_check is not None and stop_check():
                break
            job = store.get_backfill_job(job_id)
            if job is None:
                raise ValueError(f"backfill job {job_id} disappeared")
            progress = job.progress or {}
            new_completed = int(progress.get("completed_partitions") or 0)
            label = _current_backfill_partition(progress)
            while last_completed < new_completed:
                last_completed += 1
                last_progress_at = time.monotonic()
                advance(label=label or f"{last_completed}/{total}")
            ver = int(getattr(job, "version", 0) or 0)
            if ver != last_version:
                last_version = ver
                last_progress_at = time.monotonic()
                warned_stall = False
            status = (
                job.status.value if hasattr(job.status, "value") else str(job.status)
            )
            if status in terminal:
                break
            stalled_for = time.monotonic() - last_progress_at
            if not warned_stall and stalled_for >= stall_warn_seconds:
                warned_stall = True
                print_warn(
                    "no partition progress yet — is `twin runtime start` running?"
                )
            elif warned_stall and stalled_for >= stall_warn_seconds * 2:
                print_err(
                    "still no progress — start the runtime, then re-run --run"
                )
                stalled_exit = True
                break
            time.sleep(max(0.1, poll_seconds))

    job = store.get_backfill_job(job_id)
    progress = (job.progress if job else None) or {}
    status = (
        job.status.value if job and hasattr(job.status, "value")
        else (str(job.status) if job else "unknown")
    )
    out = {
        "job_id": job_id,
        "status": status,
        "completed_partitions": int(progress.get("completed_partitions") or 0),
        "total_partitions": int(progress.get("total_partitions") or 0),
        "done": status in terminal,
        "stalled": stalled_exit,
        "last_error": (job.last_error if job else None),
        "elapsed_seconds": round(time.monotonic() - started, 1),
    }
    if status == "completed":
        print_ok(
            f"backfill complete · {out['completed_partitions']}/"
            f"{out['total_partitions']} partitions"
        )
        degraded = [
            p for p in (progress.get("partitions") or [])
            if p.get("degraded")
        ]
        if degraded:
            failed_streams = sorted({
                s for p in degraded for s in (p.get("failed_streams") or [])
            })
            out["degraded_partitions"] = len(degraded)
            out["failed_streams"] = failed_streams
            print_warn(
                f"{len(degraded)} partition(s) completed degraded — "
                f"gave up on stream(s): {', '.join(failed_streams) or 'unknown'}"
            )
            print_dim(
                "these sources kept failing (e.g. bot not in channel / no "
                "access). Fix access and re-run backfill to fill the gap."
            )
    elif status == "failed":
        print_err(f"backfill failed · {(job.last_error if job else None) or 'see job status'}")
    elif status == "cancelled":
        print_warn("backfill cancelled")
    return out


@contextmanager
def spinner(text: str = "Working…") -> Iterator[None]:
    r = _rich()
    if r is None or not sys.stdout.isatty():
        print(text)
        yield
        return
    from rich.live import Live
    from rich.spinner import Spinner as RichSpinner

    with Live(
        RichSpinner("dots", text=text, style=BRAND),
        refresh_per_second=12,
        transient=True,
    ):
        yield


def _elapsed_short(started_at: str) -> str:
    if not started_at:
        return ""
    try:
        from datetime import datetime, timezone

        raw = started_at.replace("Z", "+00:00")
        t = datetime.fromisoformat(raw)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        sec = max(0, int((datetime.now(timezone.utc) - t.astimezone(timezone.utc)).total_seconds()))
        if sec < 60:
            return f"{sec}s"
        return f"{sec // 60}m{sec % 60:02d}s"
    except Exception:
        return ""


def _queue_summary(queue: dict) -> str:
    if not queue:
        return "—"
    parts = []
    for key in ("pending", "running", "failed", "completed", "dead_letter", "cancelled"):
        n = int(queue.get(key) or 0)
        if n:
            parts.append(f"{key}={n}")
    return "  ".join(parts) if parts else "empty"


def format_runtime_dashboard_plain(snap: dict) -> str:
    """One-line / multi-line plain status for non-TTY or --no-live."""
    q = _queue_summary(snap.get("queue") or {})
    inflight = []
    for w in snap.get("workers") or []:
        cur = w.get("current")
        if cur:
            inflight.append(f"{w.get('id')}:{cur.get('label') or cur.get('kind')}")
    work = ", ".join(inflight) if inflight else "idle"
    recent = snap.get("recent") or []
    last = ""
    if recent:
        ev = recent[0]
        last = f" last={ev.get('status')}:{ev.get('kind')}"
    return (
        f"runtime workers={snap.get('workers_n')} offline={snap.get('offline')} "
        f"queue[{q}] processing[{work}] done={snap.get('completed')} "
        f"fail={snap.get('failed')} dlq={snap.get('dead_letters')}{last}"
    )


def build_runtime_dashboard(snap: dict):
    """Rich renderable for ``twin runtime start`` live panel, or None if no rich."""
    r = _rich()
    if r is None:
        return None
    from rich.console import Group
    from rich.text import Text

    Table = r["Table"]
    Panel = r["Panel"]

    header = Table(show_header=False, box=None, padding=(0, 1))
    header.add_column("k", style="bold bright_magenta")
    header.add_column("v", style="bright_white")
    header.add_row("queue", _queue_summary(snap.get("queue") or {}))
    header.add_row(
        "totals",
        f"done={snap.get('completed', 0)}  fail={snap.get('failed', 0)}  "
        f"dlq={snap.get('dead_letters', 0)}  "
        f"workers={snap.get('workers_n')}  "
        f"vault={snap.get('vault_id', '*')}"
        + ("  offline" if snap.get("offline") else ""),
    )
    if snap.get("stopping"):
        header.add_row("state", "stopping…")

    workers = Table(
        show_header=True,
        header_style=BRAND_BOLD,
        box=None,
        padding=(0, 1),
        title=f"[{BRAND_BOLD}]processing[/]",
    )
    workers.add_column("worker", style=BRAND)
    workers.add_column("status")
    workers.add_column("job", overflow="fold")
    workers.add_column("age", justify="right")
    pool = snap.get("workers") or []
    if not pool:
        workers.add_row("—", "idle", "(no workers)" if snap.get("offline") else "starting…", "")
    else:
        for w in pool:
            cur = w.get("current")
            if cur:
                workers.add_row(
                    str(w.get("id") or ""),
                    f"[{WARN}]running[/]",
                    str(cur.get("label") or cur.get("kind") or ""),
                    _elapsed_short(str(cur.get("started_at") or "")),
                )
            else:
                workers.add_row(
                    str(w.get("id") or ""),
                    f"[{OK}]idle[/]",
                    "—",
                    "",
                )

    recent_t = Table(
        show_header=True,
        header_style=BRAND_BOLD,
        box=None,
        padding=(0, 1),
        title=f"[{BRAND_BOLD}]recent[/]",
    )
    recent_t.add_column("status", width=10)
    recent_t.add_column("kind")
    recent_t.add_column("job", max_width=22)
    recent_t.add_column("detail", overflow="fold")
    recent = snap.get("recent") or []
    if not recent:
        recent_t.add_row("—", "—", "—", "waiting for jobs…")
    else:
        for ev in recent[:10]:
            st = str(ev.get("status") or "")
            style = OK if st == "completed" else ERR if st == "failed" else WARN
            detail = str(ev.get("error") or ev.get("label") or "")
            jid = str(ev.get("job_id") or "")
            if len(jid) > 18:
                jid = jid[:16] + "…"
            recent_t.add_row(
                f"[{style}]{st}[/]",
                str(ev.get("kind") or ""),
                jid,
                detail,
            )

    footer = Text("Ctrl+C to stop", style="bright_black")
    body = Group(header, Text(""), workers, Text(""), recent_t, Text(""), footer)
    return Panel(
        body,
        title=f"[{BRAND_BOLD}]twin runtime[/]",
        border_style=BRAND_BORDER,
        style="white",
    )


def run_runtime_with_live(rt, *, live: bool = True) -> None:
    """Run ``TwinRuntime`` with a refreshing processing panel when possible."""
    use_live = (
        live
        and sys.stdout.isatty()
        and _rich() is not None
        and not os.environ.get("TWIN_RUNTIME_NO_LIVE")
    )
    if not use_live:
        if live and sys.stdout.isatty():
            last = [0.0]

            def plain_tick(snap: dict) -> None:
                now = time.monotonic()
                if now - last[0] < 3.0 and not snap.get("stopping"):
                    return
                last[0] = now
                print(format_runtime_dashboard_plain(snap), flush=True)

            rt.on_tick = plain_tick
        rt.run()
        return

    import logging

    from rich.live import Live

    # Keep INFO logs from fighting the Live redraw; panel is the signal.
    for name in ("twin.interfaces.runtime", "twin.interfaces.runtime.worker"):
        logging.getLogger(name).setLevel(logging.WARNING)

    renderable = build_runtime_dashboard(rt.snapshot())
    with Live(renderable, refresh_per_second=4, transient=False) as live_ui:
        def on_tick(snap: dict) -> None:
            panel = build_runtime_dashboard(snap)
            if panel is not None:
                live_ui.update(panel)

        rt.on_tick = on_tick
        rt.run()


def write_env_file(path, values: dict[str, str]) -> None:
    """Merge KEY=VALUE pairs into a dotenv-like file (preserves other keys)."""
    existing: dict[str, str] = {}
    path = __import__("pathlib").Path(path)
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            raw = line.strip()
            if not raw or raw.startswith("#") or "=" not in raw:
                continue
            k, v = raw.split("=", 1)
            existing[k.strip()] = v.strip().strip('"').strip("'")
    existing.update({k: str(v) for k, v in values.items() if v is not None})
    lines = ["# Twin local environment — loaded by twin on startup", ""]
    for k in sorted(existing):
        lines.append(f"{k}={existing[k]}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def load_env_file(path) -> dict[str, str]:
    path = __import__("pathlib").Path(path)
    out: dict[str, str] = {}
    if not path.exists():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.strip()
        if not raw or raw.startswith("#") or "=" not in raw:
            continue
        k, v = raw.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def apply_env_file(path) -> None:
    """Load ~/.twin/env into os.environ without overriding already-set vars."""
    for key, value in load_env_file(path).items():
        os.environ.setdefault(key, value)
