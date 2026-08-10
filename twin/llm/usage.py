"""LLM usage accounting — tokens, cost, latency, and where it was spent.

Every chat completion (hot-path interpret/observe and the analysis-path
reflect/pattern) emits an :class:`LLMUsage` record. Records are tagged with the
cognition *stage* and the model *role* (hot vs analysis) via a contextvar the
callers set, then written to an append-only JSONL ledger under ``~/.twin``.

This module is intentionally dependency-light and never raises into the model
path: accounting must not be able to break a completion. The CLI (`twin usage`)
reads the ledger back and aggregates it.

Cost is an *estimate*: a built-in price table (USD per 1M tokens) keyed by model
substring, overridable per home via ``pricing.json``. Local models (Ollama)
count tokens but cost 0. Unknown cloud models are flagged ``priced=False`` so a
missing price is visible rather than silently counted as free.
"""

from __future__ import annotations

import contextlib
import contextvars
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Optional

# -- record -------------------------------------------------------------------


@dataclass
class LLMUsage:
    at: str
    provider: str                 # adapter kind: ollama | openai_compatible | anthropic | gemini
    model: str
    stage: str = "other"          # interpret | observe | reflect | pattern | …
    role: str = "hot"             # hot | analysis
    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    priced: bool = False          # False ⇒ no price for this model (cost is 0/unknown)
    latency_ms: int = 0
    requests: int = 1             # HTTP attempts (retries/format fallbacks)
    ok: bool = True
    session_id: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return asdict(self)


# -- stage / role context -----------------------------------------------------

_CTX: contextvars.ContextVar[dict[str, Any]] = contextvars.ContextVar(
    "twin_llm_usage_ctx", default={}
)


@contextlib.contextmanager
def usage_context(**fields: Any):
    """Tag every usage record emitted in this scope (stage, role, session_id, …).

    Nested scopes merge; inner keys win. Example::

        with usage_context(stage="reflect", role="llm", session_id=sid):
            client.complete_json(...)
    """
    current = dict(_CTX.get())
    current.update({k: v for k, v in fields.items() if v is not None})
    token = _CTX.set(current)
    try:
        yield
    finally:
        _CTX.reset(token)


def current_context() -> dict[str, Any]:
    return dict(_CTX.get())


# -- sinks --------------------------------------------------------------------

Sink = Callable[[LLMUsage], None]
_SINKS: list[Sink] = []
_SINK_KEYS: set[str] = set()
_LOCK = threading.Lock()


def add_sink(fn: Sink, *, key: Optional[str] = None) -> None:
    """Register a usage sink. ``key`` makes registration idempotent."""
    with _LOCK:
        if key is not None:
            if key in _SINK_KEYS:
                return
            _SINK_KEYS.add(key)
        _SINKS.append(fn)


def reset_sinks() -> None:
    with _LOCK:
        _SINKS.clear()
        _SINK_KEYS.clear()


def record_usage(usage: LLMUsage) -> None:
    """Dispatch a record to all sinks. Never raises."""
    with _LOCK:
        sinks = list(_SINKS)
    for fn in sinks:
        try:
            fn(usage)
        except Exception:
            # accounting must never break the model path
            pass


# -- pricing ------------------------------------------------------------------

# USD per 1M tokens: (input, output). Keys are matched as the LONGEST substring
# of the (lowercased) model name, so "gpt-4o-mini" beats "gpt-4o".
_BUILTIN_PRICING: dict[str, tuple[float, float]] = {
    # OpenAI
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "gpt-4.1-nano": (0.10, 0.40),
    "gpt-4.1-mini": (0.40, 1.60),
    "gpt-4.1": (2.00, 8.00),
    "o4-mini": (1.10, 4.40),
    "o3-mini": (1.10, 4.40),
    "o3": (2.00, 8.00),
    # Anthropic
    "claude-haiku-4-5": (1.00, 5.00),
    "claude-3-5-haiku": (0.80, 4.00),
    "claude-3-haiku": (0.25, 1.25),
    "claude-3-5-sonnet": (3.00, 15.00),
    "claude-3-7-sonnet": (3.00, 15.00),
    "claude-sonnet-4": (3.00, 15.00),
    "claude-3-opus": (15.00, 75.00),
    "claude-opus-4": (15.00, 75.00),
    # Google
    "gemini-1.5-flash": (0.075, 0.30),
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-1.5-pro": (1.25, 5.00),
    "gemini-2.5-pro": (1.25, 10.00),
    # DeepSeek / Mistral (rough)
    "deepseek-chat": (0.27, 1.10),
    "mistral-small": (0.20, 0.60),
    "mistral-large": (2.00, 6.00),
    # Embeddings (output rate is 0 — priced on input only)
    "text-embedding-3-small": (0.02, 0.0),
    "text-embedding-3-large": (0.13, 0.0),
    "text-embedding-ada-002": (0.10, 0.0),
    "text-embedding-004": (0.0, 0.0),
}

_LOCAL_KINDS = frozenset({"ollama"})
_pricing_cache: Optional[dict[str, tuple[float, float]]] = None
_pricing_home: Optional[str] = None


def _resolve_home(home: Optional[Path]) -> Path:
    if home:
        return Path(home)
    env = os.environ.get("TWIN_HOME")
    if env:
        return Path(env)
    return Path.home() / ".twin"


def _load_pricing(home: Optional[Path]) -> dict[str, tuple[float, float]]:
    """Built-in table merged with an optional ``<home>/pricing.json`` override."""
    global _pricing_cache, _pricing_home
    home = _resolve_home(home)
    home_key = str(home)
    if _pricing_cache is not None and _pricing_home == home_key:
        return _pricing_cache
    table = dict(_BUILTIN_PRICING)
    override = Path(home) / "pricing.json"
    env_override = os.environ.get("TWIN_PRICING_PATH")
    for candidate in (override, Path(env_override) if env_override else None):
        if candidate and candidate.exists():
            try:
                raw = json.loads(candidate.read_text(encoding="utf-8"))
                for k, v in (raw or {}).items():
                    if isinstance(v, (list, tuple)) and len(v) == 2:
                        table[str(k).lower()] = (float(v[0]), float(v[1]))
                    elif isinstance(v, dict) and "input" in v and "output" in v:
                        table[str(k).lower()] = (float(v["input"]), float(v["output"]))
            except Exception:
                pass
    _pricing_cache = table
    _pricing_home = home_key
    return table


def price_for(model: str, *, home: Optional[Path] = None) -> Optional[tuple[float, float]]:
    table = _load_pricing(home)
    m = (model or "").lower()
    best: Optional[str] = None
    for key in table:
        if key in m and (best is None or len(key) > len(best)):
            best = key
    return table[best] if best else None


def estimate_cost(
    kind: str, model: str, input_tokens: int, output_tokens: int,
    *, home: Optional[Path] = None,
) -> tuple[float, bool]:
    """Return ``(cost_usd, priced)``. Local models are free; unknown → unpriced."""
    if kind in _LOCAL_KINDS:
        return 0.0, True  # local: genuinely free, so a real 0
    price = price_for(model, home=home)
    if price is None:
        return 0.0, False
    in_rate, out_rate = price
    cost = (input_tokens / 1_000_000) * in_rate + (output_tokens / 1_000_000) * out_rate
    return round(cost, 6), True


# -- token extraction ---------------------------------------------------------


def extract_tokens(kind: str, body: Any) -> tuple[int, int, int]:
    """Best-effort ``(input, output, total)`` from a provider response body."""
    if not isinstance(body, dict):
        return 0, 0, 0
    try:
        if kind == "ollama":
            in_t = int(body.get("prompt_eval_count") or 0)
            out_t = int(body.get("eval_count") or 0)
            return in_t, out_t, in_t + out_t
        if kind == "anthropic":
            u = body.get("usage") or {}
            in_t = int(u.get("input_tokens") or 0)
            in_t += int(u.get("cache_read_input_tokens") or 0)
            in_t += int(u.get("cache_creation_input_tokens") or 0)
            out_t = int(u.get("output_tokens") or 0)
            return in_t, out_t, in_t + out_t
        if kind == "gemini":
            u = body.get("usageMetadata") or {}
            in_t = int(u.get("promptTokenCount") or 0)
            out_t = int(u.get("candidatesTokenCount") or 0)
            total = int(u.get("totalTokenCount") or (in_t + out_t))
            return in_t, out_t, total
        # openai_compatible and OpenAI-shaped gateways
        u = body.get("usage") or {}
        in_t = int(u.get("prompt_tokens") or 0)
        out_t = int(u.get("completion_tokens") or 0)
        total = int(u.get("total_tokens") or (in_t + out_t))
        return in_t, out_t, total
    except (TypeError, ValueError):
        return 0, 0, 0


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit_usage(
    *,
    kind: str,
    model: str,
    body: Any,
    started: float,
    ok: bool = True,
    requests: int = 1,
    home: Optional[Path] = None,
    stage: Optional[str] = None,
    role: Optional[str] = None,
    extra: Optional[dict[str, Any]] = None,
) -> None:
    """Build and record an :class:`LLMUsage` from a completed call. Never raises.

    ``stage`` / ``role`` override the ambient :func:`usage_context` — used e.g.
    by embeddings, which are a distinct cost type regardless of the surrounding
    chat stage.
    """
    try:
        import time

        latency_ms = int(max(0.0, (time.perf_counter() - started)) * 1000)
        in_t, out_t, total = extract_tokens(kind, body)
        cost, priced = estimate_cost(kind, model, in_t, out_t, home=home)
        ctx = current_context()
        usage = LLMUsage(
            at=_now_iso(),
            provider=kind,
            model=model,
            stage=str(stage or ctx.get("stage") or "other"),
            role=str(role or ctx.get("role") or "hot"),
            input_tokens=in_t,
            output_tokens=out_t,
            total_tokens=total,
            cost_usd=cost,
            priced=priced,
            latency_ms=latency_ms,
            requests=requests,
            ok=ok,
            session_id=ctx.get("session_id"),
            meta={
                k: v for k, v in ctx.items()
                if k not in ("stage", "role", "session_id")
            } | (extra or {}),
        )
        record_usage(usage)
    except Exception:
        pass


# -- JSONL ledger -------------------------------------------------------------


def default_ledger_path(home: Path) -> Path:
    return Path(home) / "usage.jsonl"


class JsonlLedger:
    """Append-only JSONL ledger. One record per line; cross-process safe for
    small appends (a single line write is atomic on POSIX)."""

    def __init__(self, path: Path):
        self.path = Path(path)

    def record(self, usage: LLMUsage) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(usage.to_json(), separators=(",", ":"))
        with open(self.path, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")

    def read(
        self, *, since: Optional[str] = None, until: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        rows: list[dict[str, Any]] = []
        with open(self.path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                at = rec.get("at") or ""
                if since and at < since:
                    continue
                if until and at > until:
                    continue
                rows.append(rec)
        return rows


def install_ledger_sink(home: Path) -> None:
    """Install a ledger sink for ``home`` (idempotent per path)."""
    path = default_ledger_path(home)
    ledger = JsonlLedger(path)

    def _sink(usage: LLMUsage) -> None:
        ledger.record(usage)

    add_sink(_sink, key=f"ledger:{path}")


# -- aggregation --------------------------------------------------------------


def _bucket(rows: Iterable[dict[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for r in rows:
        k = str(r.get(key) or "—")
        agg = out.setdefault(k, {
            "calls": 0, "input_tokens": 0, "output_tokens": 0,
            "total_tokens": 0, "cost_usd": 0.0, "errors": 0,
        })
        agg["calls"] += 1
        agg["input_tokens"] += int(r.get("input_tokens") or 0)
        agg["output_tokens"] += int(r.get("output_tokens") or 0)
        agg["total_tokens"] += int(r.get("total_tokens") or 0)
        agg["cost_usd"] = round(agg["cost_usd"] + float(r.get("cost_usd") or 0.0), 6)
        if not r.get("ok", True):
            agg["errors"] += 1
    return out


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Totals + breakdowns by stage / model / provider / role / day."""
    totals = {
        "calls": len(rows),
        "input_tokens": sum(int(r.get("input_tokens") or 0) for r in rows),
        "output_tokens": sum(int(r.get("output_tokens") or 0) for r in rows),
        "total_tokens": sum(int(r.get("total_tokens") or 0) for r in rows),
        "cost_usd": round(sum(float(r.get("cost_usd") or 0.0) for r in rows), 6),
        "errors": sum(0 if r.get("ok", True) else 1 for r in rows),
        "unpriced_calls": sum(
            1 for r in rows
            if not r.get("priced", False) and r.get("provider") not in _LOCAL_KINDS
        ),
        "avg_latency_ms": (
            int(sum(int(r.get("latency_ms") or 0) for r in rows) / len(rows))
            if rows else 0
        ),
    }
    by_day = _bucket(
        ({**r, "_day": (r.get("at") or "")[:10]} for r in rows), "_day",
    )
    return {
        "totals": totals,
        "by_stage": _bucket(rows, "stage"),
        "by_model": _bucket(rows, "model"),
        "by_provider": _bucket(rows, "provider"),
        "by_role": _bucket(rows, "role"),
        "by_day": by_day,
    }
