"""External identity resolution (v0.6 Phase 7 §17).

Never merge people by display name alone. Email + provider ID are strong
signals; everything else stays a reviewable IdentityLink candidate.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .models import ExternalIdentity, IdentityLink, IdentityStatus

# Auto-confirm only when signals are cryptographic-ish / provider-native.
AUTO_CONFIRM_CONFIDENCE = 0.95
# Propose reviewable links above this; below is noise.
CANDIDATE_THRESHOLD = 0.55

_ACTOR_RE = re.compile(
    r"^(github|slack|mail|meeting|document|calendar):(.+)$"
)


def parse_actor_id(actor_id: str) -> tuple[Optional[str], Optional[str]]:
    """Return (provider, external_key) for a connector actor id."""
    text = (actor_id or "").strip()
    if not text:
        return None, None
    m = _ACTOR_RE.match(text)
    if not m:
        return None, text
    provider, rest = m.group(1), m.group(2)
    if provider == "mail":
        return "mail", rest.lower()
    if provider == "slack":
        # slack:{team}:{user}
        return "slack", rest
    if provider == "github":
        return "github", rest.lower()
    return provider, rest


def upsert_external_identity(
    store,
    *,
    actor_id: str,
    source_account_id: str = "",
    display_name: Optional[str] = None,
    email: Optional[str] = None,
    mapping_signals: Optional[list[str]] = None,
) -> Optional[ExternalIdentity]:
    provider, external_id = parse_actor_id(actor_id)
    if not provider or not external_id:
        return None
    existing = store.find_external_identity(
        provider=provider, external_id=external_id,
        source_account_id=source_account_id or None,
    )
    if existing is not None:
        changed = False
        if display_name and not existing.display_name:
            existing.display_name = display_name
            changed = True
        if email and not existing.email:
            existing.email = email.lower()
            changed = True
        for sig in mapping_signals or []:
            if sig not in existing.mapping_signals:
                existing.mapping_signals.append(sig)
                changed = True
        if changed:
            store.update_external_identity(existing)
        return existing

    conf = 0.9 if provider == "mail" else 0.7
    if provider == "mail" and not email:
        email = external_id
    ident = ExternalIdentity(
        provider=provider,
        external_id=external_id,
        display_name=display_name,
        email=email.lower() if email else None,
        source_account_id=source_account_id,
        actor_id=actor_id if actor_id.startswith(f"{provider}:") else f"{provider}:{external_id}",
        confidence=conf,
        confirmed=False,
        mapping_signals=list(mapping_signals or ["actor_id"]),
    )
    store.insert_external_identity(ident)
    return ident


def propose_identity_links(store, identities: list[ExternalIdentity]) -> list[IdentityLink]:
    """Propose links: same email across providers; never name-only merges."""
    created: list[IdentityLink] = []
    by_email: dict[str, list[ExternalIdentity]] = {}
    for ident in identities:
        if ident.email:
            by_email.setdefault(ident.email.lower(), []).append(ident)

    for email, group in by_email.items():
        if len(group) < 2:
            continue
        anchor = group[0]
        for other in group[1:]:
            if store.find_identity_link(anchor.id, other.id):
                continue
            conf = 0.92
            status = (
                IdentityStatus.confirmed
                if conf >= AUTO_CONFIRM_CONFIDENCE
                else IdentityStatus.candidate
            )
            # Email match is strong but still not auto-confirmed without
            # user/provider attestation — keep as candidate at 0.92.
            status = IdentityStatus.candidate
            link = IdentityLink(
                left_identity_id=anchor.id,
                right_identity_id=other.id,
                confidence=conf,
                status=status,
                signals=["shared_email", f"email:{email}"],
            )
            store.insert_identity_link(link)
            created.append(link)

    # Same provider external_id across accounts → candidate (not auto-merge entity)
    by_provider_ext: dict[tuple[str, str], list[ExternalIdentity]] = {}
    for ident in identities:
        by_provider_ext.setdefault(
            (ident.provider, ident.external_id), [],
        ).append(ident)
    for (_prov, _ext), group in by_provider_ext.items():
        if len(group) < 2:
            continue
        anchor = group[0]
        for other in group[1:]:
            if other.source_account_id == anchor.source_account_id:
                continue
            if store.find_identity_link(anchor.id, other.id):
                continue
            link = IdentityLink(
                left_identity_id=anchor.id,
                right_identity_id=other.id,
                confidence=0.80,
                status=IdentityStatus.candidate,
                signals=["same_provider_external_id"],
            )
            store.insert_identity_link(link)
            created.append(link)
    return created


def confirm_identity_link(store, link_id: str, *, entity_id: Optional[str] = None) -> IdentityLink:
    link = store.get_identity_link(link_id)
    if link is None:
        raise ValueError(f"identity link {link_id} not found")
    link.status = IdentityStatus.confirmed
    link.confidence = max(link.confidence, 0.99)
    if entity_id:
        link.entity_id = entity_id
    store.update_identity_link(link)
    # Propagate linked_entity_id onto identities when confirmed.
    if entity_id:
        for iid in (link.left_identity_id, link.right_identity_id):
            if not iid:
                continue
            ident = store.get_external_identity(iid)
            if ident is None:
                continue
            ident.linked_entity_id = entity_id
            ident.confirmed = True
            ident.confidence = max(ident.confidence, 0.99)
            store.update_external_identity(ident)
    return link


def ingest_actors_from_record(
    store, record: Any,
) -> list[ExternalIdentity]:
    """Upsert identities from a ConnectorRecord's actor/participant ids."""
    out: list[ExternalIdentity] = []
    account_id = getattr(record, "source_account_id", "") or ""
    seen: set[str] = set()
    for aid in list(getattr(record, "actor_ids", None) or []) + list(
        getattr(record, "participant_ids", None) or []
    ):
        if not aid or aid in seen:
            continue
        seen.add(aid)
        ident = upsert_external_identity(
            store, actor_id=aid, source_account_id=account_id,
            mapping_signals=["connector_record"],
        )
        if ident:
            out.append(ident)
    return out
