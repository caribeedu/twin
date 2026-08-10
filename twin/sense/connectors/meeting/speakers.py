"""Speaker mapping heuristics.

Never assume ``Speaker 1`` is a person. Confidence stays explicit; low-
confidence mappings remain candidates for review, not auto-merges.
Identities are account-scoped — never global across SourceAccounts.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .model import MeetingRecord, SpeakerIdentity, TranscriptSegment

_SPEAKER_N = re.compile(r"^speaker\s*(\d+)$", re.I)
_EMAIL = re.compile(r"[\w.+-]+@[\w.-]+\.\w+")

# Below this, actor_id stays null / meeting-local label only.
ACTOR_PROMOTE_THRESHOLD = 0.70


def actor_id_for(
    *,
    provider: str,
    account_key: str,
    meeting_id: str,
    email: Optional[str] = None,
    provider_speaker_id: Optional[str] = None,
    label: Optional[str] = None,
    confidence: float = 0.0,
) -> Optional[str]:
    if email:
        m = _EMAIL.search(email)
        if m:
            return f"mail:{m.group(0).lower()}"
    if provider_speaker_id:
        return (
            f"meeting:{provider}:{account_key}:speaker:{provider_speaker_id}"
        )
    # Unconfirmed names must not become cross-meeting identities.
    if label and confidence >= ACTOR_PROMOTE_THRESHOLD and not _SPEAKER_N.match(
        label.strip()
    ):
        slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
        if slug:
            return f"meeting:{provider}:{account_key}:name:{slug}"
    if label and not _SPEAKER_N.match(label.strip()):
        # Meeting-local candidate only — never promoted into actor_ids.
        slug = re.sub(r"[^a-z0-9]+", "-", label.strip().lower()).strip("-")
        if slug:
            return (
                f"meeting:{provider}:{account_key}:{meeting_id}:label:{slug}"
            )
    return None


def map_speakers(
    *,
    provider: str,
    account_key: str,
    meeting_id: str,
    segment_labels: list[str],
    participants: Optional[list[Any]] = None,
    organizer_email: Optional[str] = None,
    host_email: Optional[str] = None,
    provider_speaker_map: Optional[dict[str, dict[str, Any]]] = None,
) -> list[SpeakerIdentity]:
    """Build SpeakerIdentity rows from transcript labels + attendee hints."""
    participants = participants or []
    provider_speaker_map = provider_speaker_map or {}
    emails: list[str] = []
    names: dict[str, str] = {}
    for p in participants:
        if isinstance(p, str):
            if "@" in p:
                emails.append(p.lower())
            else:
                names[p.strip().lower()] = p.strip()
        elif isinstance(p, dict):
            email = (p.get("email") or "").lower() or None
            name = (p.get("name") or p.get("display_name") or "").strip()
            if email:
                emails.append(email)
            if name:
                names[name.lower()] = email or name

    seen: dict[str, SpeakerIdentity] = {}
    for label in segment_labels:
        key = label.strip()
        if not key or key in seen:
            continue
        mapped = provider_speaker_map.get(key) or provider_speaker_map.get(
            key.lower()) or {}
        email = (mapped.get("email") or "").lower() or None
        display = mapped.get("name") or mapped.get("display_name")
        provider_id = mapped.get("id") or mapped.get("speaker_id")
        signals: list[str] = []
        confidence = 0.0
        confirmed = False

        if email:
            signals.append("provider_speaker_map")
            confidence = 0.95
            confirmed = True
        elif provider_id:
            signals.append("provider_speaker_id")
            confidence = 0.85
        elif key.lower() in names:
            target = names[key.lower()]
            if isinstance(target, str) and "@" in target:
                email = target.lower()
            else:
                display = display or (target if isinstance(target, str) else key)
            signals.append("participant_name_match")
            confidence = 0.70
        elif len(emails) == 1 and not _SPEAKER_N.match(key):
            email = emails[0]
            signals.append("sole_participant_heuristic")
            confidence = 0.45
        elif (host_email or organizer_email) and not _SPEAKER_N.match(key):
            signals.append("named_speaker_unlinked")
            confidence = 0.30
        else:
            signals.append("unresolved_label")
            confidence = 0.10

        aid = actor_id_for(
            provider=provider,
            account_key=account_key,
            meeting_id=meeting_id,
            email=email,
            provider_speaker_id=str(provider_id) if provider_id else None,
            label=key,
            confidence=confidence,
        )
        # Weak provisional labels must not look like durable actors.
        if confidence < ACTOR_PROMOTE_THRESHOLD and not email and not provider_id:
            # Keep meeting-local label id for lineage, but callers filter
            # actor_ids by threshold.
            pass

        seen[key] = SpeakerIdentity(
            label=key,
            actor_id=aid,
            display_name=display or (None if _SPEAKER_N.match(key) else key),
            email=email,
            provider_speaker_id=str(provider_id) if provider_id else None,
            confidence=confidence,
            confirmed=confirmed,
            mapping_signals=signals,
        )
    return list(seen.values())


def attach_speaker_ids(
    meeting: MeetingRecord, speakers: list[SpeakerIdentity],
) -> MeetingRecord:
    by_label = {s.label: s for s in speakers}
    new_segments: list[TranscriptSegment] = []
    for seg in meeting.segments:
        sp = by_label.get(seg.speaker_label)
        new_segments.append(TranscriptSegment(
            index=seg.index,
            speaker_label=seg.speaker_label,
            text=seg.text,
            start_ms=seg.start_ms,
            end_ms=seg.end_ms,
            speaker_identity_id=(
                sp.actor_id if sp and sp.confidence >= ACTOR_PROMOTE_THRESHOLD
                else None
            ),
            confidence=sp.confidence if sp else seg.confidence,
        ))
    meeting.segments = new_segments
    meeting.speakers = speakers
    return meeting


def resolved_actor_ids(speakers: list[dict[str, Any] | SpeakerIdentity],
                       *, spoke_labels: Optional[set[str]] = None) -> list[str]:
    """Actors for cognition: confirmed/high-confidence speakers who spoke."""
    out: list[str] = []
    for sp in speakers:
        if isinstance(sp, SpeakerIdentity):
            label, aid, conf = sp.label, sp.actor_id, sp.confidence
        else:
            label = str(sp.get("label") or "")
            aid = sp.get("actor_id")
            conf = float(sp.get("confidence") or 0)
        if not aid or conf < ACTOR_PROMOTE_THRESHOLD:
            continue
        if spoke_labels is not None and label not in spoke_labels:
            continue
        if aid not in out:
            out.append(aid)
    return out
