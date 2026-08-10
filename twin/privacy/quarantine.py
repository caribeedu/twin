"""Prompt-injection quarantine — ingested content is data, never instruction."""

from __future__ import annotations

import hashlib
import re
from typing import Optional

from .. import ids
from ..clock import now_iso
from twin.store.store.base import MemoryStore
from .models import QuarantineRecord, QuarantineStatus

_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("instruction_override", re.compile(
        r"ignore\s+(all\s+)?(previous|prior|above)\s+instructions", re.I)),
    ("instruction_override", re.compile(
        r"disregard\s+(your\s+)?(system|safety)\s+(prompt|rules)", re.I)),
    ("data_exfiltration_request", re.compile(
        r"(upload|exfiltrate|dump|send)\s+(your\s+)?(memory|database|secrets?)", re.I)),
    ("policy_tamper", re.compile(
        r"(disable|bypass|override)\s+(the\s+)?(firewall|policy|privacy)", re.I)),
    ("fake_system_message", re.compile(
        r"^\s*(system|assistant)\s*:", re.I | re.M)),
    ("tool_call_injection", re.compile(
        r"<(tool_call|function_call)|invoke\s+tool", re.I)),
]


def detect_injection(text: str) -> list[str]:
    hits: list[str] = []
    for name, pat in _PATTERNS:
        if pat.search(text or ""):
            hits.append(name)
    return sorted(set(hits))


def quarantine_content(
    store: MemoryStore,
    text: str,
    *,
    artifact_id: Optional[str] = None,
    percept_id: Optional[str] = None,
    reason: str = "prompt_injection_pattern",
) -> Optional[QuarantineRecord]:
    patterns = detect_injection(text)
    if not patterns:
        return None
    fp = hashlib.sha256((text or "").encode()).hexdigest()[:24]
    if hasattr(store, "find_quarantine_by_fingerprint"):
        existing = store.find_quarantine_by_fingerprint(fp)
        if existing and existing.status == QuarantineStatus.quarantined:
            return existing
    rec = QuarantineRecord(
        id=ids.new_id("quar"),
        artifact_id=artifact_id,
        percept_id=percept_id,
        reason=reason,
        detected_patterns=patterns,
        severity="high",
        status=QuarantineStatus.quarantined,
        content_fingerprint=fp,
        created_at=now_iso(),
    )
    store.insert_quarantine(rec)
    return rec


def is_quarantined(store: MemoryStore, *, artifact_id: Optional[str] = None,
                   percept_id: Optional[str] = None,
                   content_fingerprint: Optional[str] = None) -> bool:
    if not hasattr(store, "list_quarantine"):
        return False
    for q in store.list_quarantine(status=QuarantineStatus.quarantined.value):
        if artifact_id and q.artifact_id == artifact_id:
            return True
        if percept_id and q.percept_id == percept_id:
            return True
        if content_fingerprint and q.content_fingerprint == content_fingerprint:
            return True
    return False


def release_quarantine(
    store: MemoryStore,
    quarantine_id: str,
    *,
    actor: str,
    reason: str,
    mode: str = "release_as_safe",
    confirm: bool = False,
) -> QuarantineRecord:
    """Release requires explicit actor/reason/confirm. Malicious content is not
    re-ingested automatically — caller must choose sanitized vs reject."""
    if not confirm:
        raise ValueError("release_quarantine requires confirm=True")
    if not actor or not reason:
        raise ValueError("release_quarantine requires actor and reason")
    if mode not in ("release_as_safe", "release_sanitized", "reject"):
        raise ValueError("mode must be release_as_safe | release_sanitized | reject")

    rec = store.get_quarantine(quarantine_id)
    if rec is None:
        raise ValueError(f"quarantine {quarantine_id} not found")
    if rec.status != QuarantineStatus.quarantined:
        raise ValueError(f"quarantine is {rec.status.value}")

    if mode == "reject":
        status = QuarantineStatus.rejected
    elif mode == "release_sanitized":
        status = QuarantineStatus.released_sanitized
    else:
        status = QuarantineStatus.released

    meta = dict(rec.metadata or {})
    meta.update({
        "release_actor": actor,
        "release_reason": reason,
        "release_mode": mode,
        "released_at": now_iso(),
        # Original malicious content must not re-enter pipeline by status flip alone
        "reprocess": False if mode != "release_sanitized" else "requires_sanitization_plan",
    })
    store.update_quarantine(
        quarantine_id,
        status=status.value,
        resolved_at=now_iso(),
        metadata=meta,
    )
    return store.get_quarantine(quarantine_id)  # type: ignore[return-value]


def reject_quarantine(
    store: MemoryStore,
    quarantine_id: str,
    *,
    actor: str = "user",
    reason: str = "rejected",
) -> QuarantineRecord:
    return release_quarantine(
        store, quarantine_id,
        actor=actor, reason=reason, mode="reject", confirm=True,
    )
