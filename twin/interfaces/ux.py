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
