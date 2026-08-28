"""Continuous attention evaluation — low-intrusion, policy-gated.

Not an autonomous agent. Consumes session working memory (checkpoint + recent
deltas), runs workspace/recall signals, and emits typed outcomes only when
expected value clears the interruption threshold. Default is silence.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any, Optional

from twin import ids
from twin.clock import now_iso
from twin.config import Config
from twin.store.embeddings import Embedder
from twin.store.store.base import TwinStore


class AttentionKind(str, Enum):
    silence = "silence"
    passive_context = "passive_context"
    suggestion = "suggestion"
    contradiction_alert = "contradiction_alert"
    prior_decision_reminder = "prior_decision_reminder"
    domain_warning = "domain_warning"
    clarification_ask = "clarification_ask"
    memory_candidate = "memory_candidate"
    session_closure_item = "session_closure_item"


@dataclass
class AttentionPolicy:
    """Conceptual expected_value gates — prefer silence."""

    interrupt_threshold: float = 0.45
    cooldown_seconds: int = 120
    max_emissions_per_window: int = 3
    window_seconds: int = 600
    privacy_block_penalty: float = 0.5
    interruption_cost: float = 0.2
    sliding_window_events: int = 12


@dataclass
class AttentionOutcome:
    id: str = field(default_factory=ids.attention_emission_id)
    session_id: str = ""
    kind: AttentionKind = AttentionKind.silence
    claim_id: str = ""
    summary: str = ""
    reason: str = ""
    expected_value: float = 0.0
    relevance: float = 0.0
    confidence: float = 0.0
    status: str = "open"  # open | superseded | cancelled | accepted | suppressed
    created_at: str = field(default_factory=now_iso)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["kind"] = self.kind.value if isinstance(self.kind, AttentionKind) else str(self.kind)
        return d


def text_content_hash(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:24]


def working_memory_text(
    store: TwinStore,
    session_id: str,
    *,
    window: int = 12,
) -> str:
    """Build sliding-window text from latest checkpoint + recent deltas."""
    parts: list[str] = []
    if hasattr(store, "list_session_checkpoints"):
        cps = store.list_session_checkpoints(session_id, limit=50)
        if cps:
            last = cps[-1]
            if last.summary:
                parts.append(f"[checkpoint] {last.summary}")
            if last.active_goal:
                parts.append(f"[goal] {last.active_goal}")
    if hasattr(store, "list_session_events"):
        events = store.list_session_events(session_id, limit=10_000)
        deltas = [
            e for e in events
            if e.kind in ("delta", "note") and (e.payload or {}).get("text")
        ]
        for e in deltas[-window:]:
            parts.append(str((e.payload or {}).get("text") or ""))
    session = store.get_session(session_id) if hasattr(store, "get_session") else None
    if session and not parts and session.initial_query:
        parts.append(session.initial_query)
    return "\n".join(p for p in parts if p).strip()


def expected_value(
    *,
    relevance: float,
    confidence: float,
    timeliness: float,
    actionability: float,
    interruption_cost: float,
    privacy_risk: float,
    repetition_penalty: float,
) -> float:
    return (
        relevance * confidence * timeliness * actionability
        - interruption_cost
        - privacy_risk
        - repetition_penalty
    )


def _parse_iso(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _in_cooldown(store: TwinStore, session_id: str, policy: AttentionPolicy) -> bool:
    if not hasattr(store, "list_attention_emissions"):
        return False
    recent = [
        e for e in store.list_attention_emissions(session_id, status="open", limit=20)
        if (e.kind.value if hasattr(e.kind, "value") else str(e.kind)) != "silence"
    ]
    if not recent:
        return False
    latest = max((_parse_iso(e.created_at) for e in recent), default=None)
    if latest is None:
        return False
    return datetime.now(timezone.utc) - latest < timedelta(seconds=policy.cooldown_seconds)


def _window_count(store: TwinStore, session_id: str, policy: AttentionPolicy) -> int:
    if not hasattr(store, "list_attention_emissions"):
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=policy.window_seconds)
    n = 0
    for e in store.list_attention_emissions(session_id, limit=50):
        if e.status not in ("open", "accepted"):
            continue
        ts = _parse_iso(e.created_at)
        if ts and ts >= cutoff:
            n += 1
    return n


def _already_emitted(store: TwinStore, session_id: str, claim_id: str, kind: str) -> bool:
    if not claim_id or not hasattr(store, "list_attention_emissions"):
        return False
    for e in store.list_attention_emissions(session_id, status="open", limit=50):
        if e.claim_id == claim_id and (
            e.kind.value if hasattr(e.kind, "value") else str(e.kind)
        ) == kind:
            return True
    return False


def evaluate_attention(
    store: TwinStore,
    cfg: Config,
    embedder: Embedder,
    session_id: str,
    *,
    text: Optional[str] = None,
    policy: Optional[AttentionPolicy] = None,
) -> list[AttentionOutcome]:
    """Evaluate attention for a session. Prefer silence. Never confirms Memory."""
    from twin.cognize.services.workspace import workspace_tick
    from twin.config import UNCLASSIFIED_DOMAIN

    policy = policy or AttentionPolicy()
    session = store.get_session(session_id)
    if session is None:
        return [AttentionOutcome(
            session_id=session_id, kind=AttentionKind.silence,
            reason="session_not_found", status="cancelled",
        )]

    text = (text or working_memory_text(
        store, session_id, window=policy.sliding_window_events,
    )).strip()
    if not text:
        return [AttentionOutcome(
            session_id=session_id, kind=AttentionKind.silence,
            reason="empty_working_memory",
        )]

    if _in_cooldown(store, session_id, policy):
        return [AttentionOutcome(
            session_id=session_id, kind=AttentionKind.silence,
            reason="cooldown",
        )]
    if _window_count(store, session_id, policy) >= policy.max_emissions_per_window:
        return [AttentionOutcome(
            session_id=session_id, kind=AttentionKind.silence,
            reason="emission_cap",
        )]

    if hasattr(store, "supersede_attention_emissions"):
        store.supersede_attention_emissions(session_id, reason="reevaluate")

    tick = workspace_tick(
        store, cfg, embedder, text,
        session_id=session_id,
        target_domain=session.domain if session.domain != UNCLASSIFIED_DOMAIN else None,
        interpret=False,
        input_mode="snapshot",
        idempotency_key=f"attention:{session_id}:{text_content_hash(text)}",
    )

    candidates: list[AttentionOutcome] = []

    if tick.inferred_domain == UNCLASSIFIED_DOMAIN:
        candidates.append(AttentionOutcome(
            session_id=session_id,
            kind=AttentionKind.clarification_ask,
            summary="Domain unclear — confirm before packing context",
            reason="unclassified_domain",
            expected_value=0.6,
            relevance=0.8,
            confidence=0.7,
        ))

    if (
        tick.inferred_domain
        and session.domain
        and tick.inferred_domain != session.domain
        and tick.inferred_domain != UNCLASSIFIED_DOMAIN
    ):
        candidates.append(AttentionOutcome(
            session_id=session_id,
            kind=AttentionKind.domain_warning,
            summary=(
                f"Inferred domain {tick.inferred_domain} "
                f"differs from session {session.domain}"
            ),
            reason="domain_mismatch",
            expected_value=0.55,
            relevance=0.7,
            confidence=0.65,
            payload={"inferred": tick.inferred_domain, "session_domain": session.domain},
        ))

    for mid in tick.contradiction_claim_ids or []:
        if _already_emitted(store, session_id, mid, AttentionKind.contradiction_alert.value):
            continue
        candidates.append(AttentionOutcome(
            session_id=session_id,
            kind=AttentionKind.contradiction_alert,
            claim_id=mid,
            summary="Possible contradiction with prior memory",
            reason="salience_contradiction",
            expected_value=0.7,
            relevance=0.85,
            confidence=0.7,
        ))

    for sug in tick.suggestions or []:
        mid = sug.get("claim_id") or ""
        conf = float(sug.get("confidence") or 0)
        rel = float(sug.get("score") if sug.get("score") is not None else 0)
        kind = AttentionKind.suggestion
        blob = (sug.get("summary") or sug.get("title") or "").lower()
        if "decision" in blob or sug.get("type") == "decision":
            kind = AttentionKind.prior_decision_reminder
        if _already_emitted(store, session_id, mid, kind.value):
            continue
        if hasattr(store, "is_attention_suppressed") and store.is_attention_suppressed(
            session_id, kind=kind.value, claim_id=mid,
        ):
            continue
        privacy_risk = policy.privacy_block_penalty if any(
            b.get("claim_id") == mid for b in (tick.blocked or [])
        ) else 0.0
        ev = expected_value(
            relevance=max(rel, 0.01),
            confidence=max(conf, 0.01),
            timeliness=0.85,
            actionability=0.75 if kind == AttentionKind.prior_decision_reminder else 0.55,
            interruption_cost=policy.interruption_cost,
            privacy_risk=privacy_risk,
            repetition_penalty=0.0,
        )
        if ev < policy.interrupt_threshold:
            continue
        candidates.append(AttentionOutcome(
            session_id=session_id,
            kind=kind,
            claim_id=mid,
            summary=sug.get("summary") or sug.get("title") or mid,
            reason=sug.get("why_relevant") or "recall",
            expected_value=round(ev, 4),
            relevance=rel,
            confidence=conf,
            payload={"tick_id": tick.tick_id},
        ))

    for mid in tick.candidate_claim_ids or []:
        candidates.append(AttentionOutcome(
            session_id=session_id,
            kind=AttentionKind.memory_candidate,
            claim_id=mid,
            summary="New review candidate from interpretation",
            reason="parallel_interpretation",
            expected_value=0.5,
            relevance=0.6,
            confidence=0.6,
        ))

    survivors = [
        o for o in candidates
        if o.expected_value >= policy.interrupt_threshold
    ]
    survivors.sort(key=lambda o: o.expected_value, reverse=True)
    room = max(0, policy.max_emissions_per_window - _window_count(store, session_id, policy))
    survivors = survivors[:room]

    if not survivors:
        silence = AttentionOutcome(
            session_id=session_id,
            kind=AttentionKind.silence,
            reason=tick.silence_reason or "below_threshold",
            status="closed",
            payload={"tick_id": tick.tick_id, "silent": tick.silent},
        )
        if hasattr(store, "insert_attention_emission"):
            store.insert_attention_emission(silence)
        return [silence]

    for o in survivors:
        if o.kind == AttentionKind.suggestion and o.expected_value < policy.interrupt_threshold + 0.1:
            o.kind = AttentionKind.passive_context
        if hasattr(store, "insert_attention_emission"):
            store.insert_attention_emission(o)
    return survivors


def feedback_attention(
    store: TwinStore,
    emission_id: str,
    *,
    verdict: str,
) -> Optional[AttentionOutcome]:
    """Apply user feedback: useful→accepted; suppress/irrelevant→suppressed."""
    if not hasattr(store, "get_attention_emission"):
        return None
    em = store.get_attention_emission(emission_id)
    if em is None:
        return None
    if verdict in ("useful", "accepted"):
        em.status = "accepted"
    elif verdict in ("irrelevant", "suppress", "harmful"):
        em.status = "suppressed"
        if hasattr(store, "add_attention_suppression"):
            kind_s = em.kind.value if hasattr(em.kind, "value") else str(em.kind)
            store.add_attention_suppression(
                em.session_id, kind=kind_s, claim_id=em.claim_id,
            )
    else:
        return em
    store.update_attention_emission(em)
    return em


def maybe_enqueue_attention_job(store: TwinStore, session_id: str, *, text: str = "") -> str:
    """Enqueue durable attention_evaluate job if runtime store is available."""
    if not hasattr(store, "insert_runtime_job"):
        return ""
    from twin.interfaces.runtime.models import JobKind
    from twin.interfaces.runtime.queue import RuntimeQueue
    job = RuntimeQueue(store).enqueue(
        JobKind.attention_evaluate,
        payload={"session_id": session_id, "text": text},
        idempotency_key=f"attention_eval:{session_id}:{text_content_hash(text) or 'wm'}",
        priority=40,
        vault_id="vault_general",
    )
    return job.id
