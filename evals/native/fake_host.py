"""Fake host — proves the universal native contract without claude_code."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path

from twin import ids
from twin.config import Config
from twin.interfaces.native.events import HostCapabilities, HostEvent
from twin.interfaces.native.service import NativeHostService
from twin.store.embeddings import get_embedder
from twin.store.models import MemoryItem, MemoryStatus, MemoryType
from twin.store.store.sqlite import SqliteStore

# Claude-specific hook names / adapter imports must stay out of the generic
# service and cognition host-session modules. Provider names may appear only
# in the adapter frontier (registry / claude_code). Twin type names like
# SessionStart are fine; these strings are Claude Code hook identifiers only.
_CLAUDE_HOOK_NAMES = (
    "UserPromptSubmit",
    "PreToolUse",
    "PostToolUse",
)
_VENDOR_BRANCH_RE = re.compile(
    r"""host_type\s*==\s*["']claude-code["']"""
    r"""|["']claude-code["']\s*==\s*host_type"""
)


def normalize_fake_host(payload: dict) -> HostEvent:
    """Minimal adapter: provider JSON → HostEvent. No Claude imports."""
    default_caps = HostCapabilities.fake_host().model_dump()
    meta = payload.get("metadata") or {}
    # Caller-supplied host_capabilities replace the default profile.
    caps = meta.get("host_capabilities", default_caps)
    merged = {**meta, "host_capabilities": caps}
    return HostEvent(
        kind=payload["kind"],
        host_type="fake-host",
        external_session_id=payload["external_session_id"],
        text=payload.get("text", ""),
        event_id=payload.get("event_id"),
        domain=payload.get("domain"),
        metadata=merged,
    )


def _fake_env():
    """Isolated store/cfg/embedder for a fake-host eval case."""
    tmp = tempfile.TemporaryDirectory()
    home = Path(tmp.name) / "twin-home"
    home.mkdir()
    store = SqliteStore(home / "twin.db")
    cfg = Config(home=home)
    cfg.extractor = "echo"
    cfg.embedder = "hash"
    cfg.db_url = f"sqlite:///{home / 'twin.db'}"
    cfg.ensure_home()
    embedder = get_embedder(cfg.embedder, cfg.embedding_dim)
    return tmp, store, cfg, embedder


def _seed_memory(store, embedder, *, title: str, summary: str, domain: str = "technical"):
    mem = MemoryItem(
        id=ids.memory_id(),
        type=MemoryType.decision,
        domain=domain,
        title=title,
        summary=summary,
        status=MemoryStatus.confirmed,
        confidence=0.9,
    )
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name, embedder.embed(f"{title}\n{summary}"),
    )
    return mem


def _assert_no_vendor_coupling() -> tuple[bool, str]:
    """Generic modules must not import adapters or branch on Claude."""
    import twin.cognition.host_session as hs
    import twin.interfaces.native.service as ns

    for mod in (hs, ns):
        text = Path(mod.__file__).read_text(encoding="utf-8")
        if "from .claude_code" in text or "from twin.interfaces.native.claude_code" in text:
            return False, f"{mod.__name__} imports claude_code adapter"
        if "import twin.interfaces.native.claude_code" in text:
            return False, f"{mod.__name__} imports claude_code adapter"
        # service may import adapters.registry (frontier); never claude_code.
        if mod is ns and "claude_code" in text:
            return False, f"{mod.__name__} mentions claude_code"
        if _VENDOR_BRANCH_RE.search(text):
            return False, f"{mod.__name__} branches on host_type == claude-code"
        for hook in _CLAUDE_HOOK_NAMES:
            if hook in text:
                return False, f"{mod.__name__} contains Claude hook name {hook!r}"
    return True, "ok"


def run_fake_host_case() -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "twin-home"
        home.mkdir()
        store = SqliteStore(home / "twin.db")
        cfg = Config(home=home)
        cfg.extractor = "echo"
        cfg.embedder = "hash"
        cfg.db_url = f"sqlite:///{home / 'twin.db'}"
        cfg.ensure_home()
        embedder = get_embedder(cfg.embedder, cfg.embedding_dim)
        svc = NativeHostService(store, cfg, embedder)
        ext = "fake-eval-1"

        start = svc.handle(normalize_fake_host({
            "kind": "session_start",
            "external_session_id": ext,
            "text": "portable native contract",
            "domain": "technical",
        }))
        if not start.ok:
            return False, f"start failed: {start.error}"
        if start.binding.host_type != "fake-host":
            return False, "host_type not preserved"
        ses = store.get_session(start.session_id)
        if ses is None or ses.tool_id != "native-host":
            return False, f"expected tool_id=native-host got {getattr(ses, 'tool_id', None)}"
        if ses.client != "fake-host":
            return False, f"expected client=fake-host got {ses.client}"

        turn = svc.handle(normalize_fake_host({
            "kind": "turn_completed",
            "external_session_id": ext,
            "event_id": "turn-1",
        }))
        if not turn.ok or turn.binding.ended_at:
            return False, "turn_completed must not close binding"

        end = svc.handle(normalize_fake_host({
            "kind": "session_end",
            "external_session_id": ext,
            "text": "done",
        }))
        if not end.ok or not end.binding.ended_at:
            return False, "session_end must close once"

        ok, msg = _assert_no_vendor_coupling()
        if not ok:
            return False, msg
        return True, "ok"


def run_security_case() -> tuple[bool, str]:
    """Security: unclassified sessions leak no domain memories; upgrade won't widen."""
    tmp, store, cfg, embedder = _fake_env()
    with tmp:
        _seed_memory(
            store, embedder,
            title="Atlas webhook stack",
            summary="Atlas webhooks run on FastAPI with schema_version.",
        )
        svc = NativeHostService(store, cfg, embedder)
        ext = "sec-eval-1"
        start = svc.handle(normalize_fake_host({
            "kind": "session_start",
            "external_session_id": ext,
            "text": "native host session",  # no domain signal → unclassified
        }))
        if not start.ok:
            return False, f"start failed: {start.error}"
        if start.binding.domain != "unclassified":
            return False, f"expected unclassified, got {start.binding.domain}"
        if start.sources:
            return False, "unclassified pack leaked domain memories"
        if "webhook" in (start.context_pack or "").lower():
            return False, "unclassified pack leaked memory content"

        b0 = start.binding
        persona0, purpose0, audience0 = b0.persona, b0.purpose, b0.audience
        principal0, vault0 = b0.principal_id, b0.vault_id

        msg = svc.handle(normalize_fake_host({
            "kind": "user_message",
            "external_session_id": ext,
            "text": "What retry strategy did we decide for Atlas webhooks?",
        }))
        if not msg.ok:
            return False, f"user_message failed: {msg.error}"
        if msg.binding.domain != "technical":
            return False, "domain did not upgrade from dialogue signal"
        widened = (
            msg.binding.persona != persona0
            or msg.binding.purpose != purpose0
            or msg.binding.audience != audience0
            or msg.binding.principal_id != principal0
            or msg.binding.vault_id != vault0
        )
        if widened:
            return False, "domain upgrade widened auth identity"
        return True, "ok"


def run_caps_case() -> tuple[bool, str]:
    """Caps: host without user_message injection holds the pack on that kind."""
    tmp, store, cfg, embedder = _fake_env()
    with tmp:
        _seed_memory(
            store, embedder,
            title="Atlas webhook stack",
            summary="Atlas webhooks run on FastAPI with schema_version.",
        )
        svc = NativeHostService(store, cfg, embedder)
        ext = "caps-eval-1"
        # Broad observation surface, but only session_start may inject packs.
        caps = HostCapabilities.fake_host().model_copy(update={
            "context_injection_events": ["session_start"],
        }).model_dump()
        start = svc.handle(normalize_fake_host({
            "kind": "session_start",
            "external_session_id": ext,
            "text": "native host session",
            "metadata": {"host_capabilities": caps},
        }))
        if not start.ok:
            return False, f"start failed: {start.error}"
        msg = svc.handle(normalize_fake_host({
            "kind": "user_message",
            "external_session_id": ext,
            "text": "What retry strategy did we decide for Atlas webhooks?",
        }))
        if not msg.ok:
            return False, f"user_message failed: {msg.error}"
        if msg.binding.domain != "technical":
            return False, "domain must still upgrade (host-independent)"
        if msg.context_pack is not None:
            return False, "pack emitted where host cannot inject"
        if not msg.extras.get("pack_held_no_injection_point"):
            return False, "missing pack_held_no_injection_point flag"
        if not msg.binding.metadata.get("pending_context_pack"):
            return False, "held pack must be marked pending_context_pack"
        if msg.binding.metadata.get("pending_context_reason") != "no_injection_point":
            return False, "expected pending_context_reason=no_injection_point"
        return True, "ok"


def run_budget_case() -> tuple[bool, str]:
    """Budget: a blown deadline skips the pack, keeps binding + marks pending."""
    import twin.interfaces.native.service as ns

    tmp, store, cfg, embedder = _fake_env()
    with tmp:
        svc = NativeHostService(store, cfg, embedder)
        ext = "budget-eval-1"
        saved = dict(ns._PACK_BUDGET_MS)
        ns._PACK_BUDGET_MS = {"session_start": 0.0001, "user_message": 0.0001}
        try:
            start = svc.handle(normalize_fake_host({
                "kind": "session_start",
                "external_session_id": ext,
                "text": "native host session",
                "domain": "technical",
            }))
        finally:
            ns._PACK_BUDGET_MS = saved
        if not start.ok or start.binding is None:
            return False, "session_start must persist binding under budget skip"
        if start.context_pack is not None:
            return False, "pack should be skipped when over budget"
        if not start.extras.get("pack_skipped_budget"):
            return False, "missing pack_skipped_budget flag"
        if not start.binding.metadata.get("pending_context_pack"):
            return False, "skipped pack must be marked pending_context_pack"
        if start.binding.metadata.get("pending_context_reason") != "latency_budget":
            return False, "expected pending_context_reason=latency_budget"
        return True, "ok"


CONTRACT_CASES = (
    ("fake_host_contract", run_fake_host_case),
    ("fake_host_security", run_security_case),
    ("fake_host_caps", run_caps_case),
    ("fake_host_budget", run_budget_case),
)


if __name__ == "__main__":
    failed = 0
    for name, fn in CONTRACT_CASES:
        ok, msg = fn()
        print(f"[{'PASS' if ok else 'FAIL'}] {name}: {msg}")
        failed += 0 if ok else 1
    raise SystemExit(0 if not failed else 1)
