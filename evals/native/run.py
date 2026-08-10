"""Run native-host eval cases."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from twin.cognize.services.sessions import start_session
from twin.config import Config
from twin.interfaces.native.claude_code import (
    MissingExternalSessionId,
    normalize_claude_code_hook,
)
from twin.interfaces.native.events import HostEvent
from twin.interfaces.native.service import NativeHostService
from twin.store.embeddings import get_embedder
from twin.store.store.sqlite import SqliteStore

CASES = Path(__file__).parent / "cases"


def _confirmed_ids(store) -> set[str]:
    return {
        m.id for m in store.list_claims(limit=5000)
        if getattr(m.status, "value", m.status) == "confirmed"
    }


def _run_case(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "twin-home"
        home.mkdir()
        store = SqliteStore(home / "twin.db")
        cfg = Config(home=home)
        cfg.extractor = "echo"   # deterministic offline interpreter (no LLM)
        cfg.embedder = "hash"
        cfg.db_url = f"sqlite:///{home / 'twin.db'}"
        cfg.ensure_home()
        embedder = get_embedder(cfg.embedder, cfg.embedding_dim)
        svc = NativeHostService(store, cfg, embedder)
        host = case.get("host_type", "claude-code")
        ext = case["external_session_id"]
        before = _confirmed_ids(store)

        # Reject cwd-only identity
        try:
            normalize_claude_code_hook(
                {"hook_event_name": "SessionStart", "cwd": "/tmp/x", "prompt": "no id"}
            )
            return False, "cwd fallback should have been rejected"
        except MissingExternalSessionId:
            pass

        hook = normalize_claude_code_hook(
            {
                "hook_event_name": "SessionStart",
                "session_id": ext,
                "cwd": "/tmp/eval-twin",
                "prompt": "prove native and MCP share one core",
                "domain": case.get("domain", "technical"),
            }
        )
        hook.domain = case.get("domain", "technical")
        start = svc.handle(hook)
        if not start.ok:
            return False, f"session_start failed: {start.error}"
        if start.context_pack is None:
            return False, "session_start returned no context_pack field"

        pack2 = svc.handle(HostEvent(
            kind="pack_request", host_type=host, external_session_id=ext,
            text="proactive pack refresh", domain=case.get("domain", "technical"),
        ))
        if not pack2.ok or pack2.session_id != start.session_id:
            return False, "pack_request not idempotent on open binding"

        # Domain freeze
        bad = svc.handle(HostEvent(
            kind="pack_request", host_type=host, external_session_id=ext,
            text="widen", domain="personal",
        ))
        if bad.ok:
            return False, "domain freeze not enforced"

        for kind, text, eid in (
            ("user_message", "how does HostSessionBinding work?", "um1"),
            ("tool_requested", "pytest --collect", "tr1"),
            ("tool_completed", "pytest passed", "tc1"),
            ("file_context", "edited adapter.py", "fc1"),
            ("assistant_result", "explained binding model", "ar1"),
        ):
            r = svc.handle(HostEvent(
                kind=kind, host_type=host, external_session_id=ext,
                text=text, event_id=eid,
            ))
            if not r.ok:
                return False, f"{kind} failed: {r.error}"
            # idempotent retry
            r2 = svc.handle(HostEvent(
                kind=kind, host_type=host, external_session_id=ext,
                text=text, event_id=eid,
            ))
            if not r2.ok or not r2.extras.get("duplicated"):
                return False, f"{kind} retry not idempotent"

        other = start_session(
            store, cfg, embedder, "parallel mcp/cli session",
            client="cli", domain=case.get("domain", "technical"),
        )
        if other.session.id == start.session_id:
            return False, "parallel session collided with native session"

        end = svc.handle(HostEvent(
            kind="session_end", host_type=host, external_session_id=ext,
            summary="Native proof complete; MCP still available.",
        ))
        if not end.ok or not end.binding or not end.binding.ended_at:
            return False, "session_end did not close binding"

        # Reuse external id → new occurrence
        again = svc.handle(HostEvent(
            kind="session_start", host_type=host, external_session_id=ext,
            text="second conversation", domain=case.get("domain", "technical"),
        ))
        if not again.ok or again.binding.occurrence != 2:
            return False, "reuse after SessionEnd did not open occurrence 2"
        if again.session_id == start.session_id:
            return False, "reuse attached to old CognitiveSession"

        after = _confirmed_ids(store)
        if after - before:
            return False, f"native path confirmed memories: {after - before}"

        return True, "ok"


def main() -> int:
    cases = sorted(CASES.glob("*.json"))
    if not cases:
        print("no native eval cases", file=sys.stderr)
        return 1
    failed = 0
    for path in cases:
        case = json.loads(path.read_text())
        ok, detail = _run_case(case)
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {case.get('id', path.stem)}: {detail}")
        if not ok:
            failed += 1

    from evals.native.fake_host import CONTRACT_CASES
    for name, fn in CONTRACT_CASES:
        ok, detail = fn()
        tag = "PASS" if ok else "FAIL"
        print(f"[{tag}] {name}: {detail}")
        if not ok:
            failed += 1
    total = len(cases) + len(CONTRACT_CASES)
    print(f"\n{total - failed}/{total} native eval cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
