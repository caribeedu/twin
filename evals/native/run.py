"""Run Phase 8 native-host eval cases."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from twin.cognition.sessions import start_session
from twin.config import Config
from twin.interfaces.native.claude_code import normalize_claude_code_hook
from twin.interfaces.native.events import HostEvent
from twin.interfaces.native.service import NativeHostService
from twin.memory.embeddings import get_embedder
from twin.memory.models import MemoryStatus
from twin.memory.store.sqlite import SqliteStore

CASES = Path(__file__).parent / "cases"


def _run_case(case: dict) -> tuple[bool, str]:
    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "twin-home"
        home.mkdir()
        store = SqliteStore(home / "twin.db")
        cfg = Config(home=home)
        cfg.extractor = "heuristic"
        cfg.embedder = "hash"
        cfg.db_url = f"sqlite:///{home / 'twin.db'}"
        cfg.ensure_home()
        embedder = get_embedder(cfg.embedder, cfg.embedding_dim)
        svc = NativeHostService(store, cfg, embedder)
        host = case.get("host_type", "claude-code")
        ext = case["external_session_id"]

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
        if not start.session_id or not start.binding:
            return False, "missing session or binding"

        pack2 = svc.handle(HostEvent(
            kind="pack_request", host_type=host, external_session_id=ext,
            text="proactive pack refresh", domain=case.get("domain", "technical"),
        ))
        if not pack2.ok or pack2.session_id != start.session_id:
            return False, "pack_request not idempotent on binding"

        for kind, text, ref in (
            ("user_message", "how does HostSessionBinding work?", None),
            ("tool_execution", "pytest tests/test_native_host_phase8.py", "Bash"),
            ("file_context", "edited adapter.py", "twin/interfaces/native/claude_code/adapter.py"),
            ("assistant_result", "explained binding model", None),
        ):
            r = svc.handle(HostEvent(
                kind=kind, host_type=host, external_session_id=ext,
                text=text, ref=ref,
            ))
            if not r.ok:
                return False, f"{kind} failed: {r.error}"

        # Parallel MCP/CLI session on the same store
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

        ses = store.get_session(start.session_id)
        if ses is None:
            return False, "cognitive session missing"
        for mid in ses.created_memory_ids or []:
            mem = store.get_memory(mid)
            if mem is not None and mem.status == MemoryStatus.confirmed:
                return False, f"native path confirmed memory {mid}"

        kinds = {a.get("kind") for a in ses.artifacts}
        for need in ("user_message", "tool_execution", "file_context"):
            if need not in kinds:
                return False, f"missing artifact kind {need}"

        # MCP-readable binding
        found = store.find_host_session_binding(host_type=host, external_session_id=ext)
        if found is None or found.cognitive_session_id != start.session_id:
            return False, "binding not readable for MCP coexistence"
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
    total = len(cases)
    print(f"\n{total - failed}/{total} native eval cases passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
