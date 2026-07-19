"""External identity resolution (v0.6 Phase 7 §17).

Never merge people by display name alone. Email + provider ID are strong
signals within the same vault; cross-vault auto-links are never proposed.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from .models import ExternalIdentity, IdentityLink, IdentityStatus
from .partition import account_meta

AUTO_CONFIRM_CONFIDENCE = 0.95
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
        return "slack", rest
    if provider == "github":
        return "github", rest.lower()
    return provider, rest


def _ordered_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a <= b else (b, a)


def upsert_external_identity(
    store,
    *,
    actor_id: str,
    source_account_id: str = "",
    vault_id: str = "",
    source_owner: str = "",
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
        if vault_id and not existing.vault_id:
            existing.vault_id = vault_id
            changed = True
        if source_owner and not existing.source_owner:
            existing.source_owner = source_owner
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
        vault_id=vault_id or "vault_unknown",
        source_owner=source_owner,
        actor_id=actor_id if actor_id.startswith(f"{provider}:") else f"{provider}:{external_id}",
        confidence=conf,
        confirmed=False,
        mapping_signals=list(mapping_signals or ["actor_id"]),
    )
    store.insert_external_identity(ident)
    return ident


def propose_identity_links(store, identities: list[ExternalIdentity]) -> list[IdentityLink]:
    """Propose links only within the same vault. Never name-only merges."""
    created: list[IdentityLink] = []
    by_vault_email: dict[tuple[str, str], list[ExternalIdentity]] = {}
    for ident in identities:
        if not ident.email:
            continue
        vault = ident.vault_id or "vault_unknown"
        by_vault_email.setdefault((vault, ident.email.lower()), []).append(ident)

    for (vault, email), group in by_vault_email.items():
        if len(group) < 2:
            continue
        anchor = group[0]
        for other in group[1:]:
            if (other.vault_id or "vault_unknown") != vault:
                continue  # belt-and-suspenders
            left, right = _ordered_pair(anchor.id, other.id)
            if store.find_identity_link(left, right):
                continue
            link = IdentityLink(
                left_identity_id=left,
                right_identity_id=right,
                vault_id=vault,
                cross_domain=False,
                confidence=0.92,
                status=IdentityStatus.candidate,
                signals=["shared_email", f"email:{email}", f"vault:{vault}"],
            )
            store.insert_identity_link(link)
            created.append(link)

    # Same provider external_id across accounts **within vault**
    by_vault_prov: dict[tuple[str, str, str], list[ExternalIdentity]] = {}
    for ident in identities:
        vault = ident.vault_id or "vault_unknown"
        by_vault_prov.setdefault(
            (vault, ident.provider, ident.external_id), [],
        ).append(ident)
    for (vault, _prov, _ext), group in by_vault_prov.items():
        if len(group) < 2:
            continue
        anchor = group[0]
        for other in group[1:]:
            if other.source_account_id == anchor.source_account_id:
                continue
            left, right = _ordered_pair(anchor.id, other.id)
            if store.find_identity_link(left, right):
                continue
            link = IdentityLink(
                left_identity_id=left,
                right_identity_id=right,
                vault_id=vault,
                cross_domain=False,
                confidence=0.80,
                status=IdentityStatus.candidate,
                signals=["same_provider_external_id", f"vault:{vault}"],
            )
            store.insert_identity_link(link)
            created.append(link)
    return created


def _refresh_identity_confirmation(store, identity_id: Optional[str]) -> None:
    """Clear ExternalIdentity.confirmed when no confirmed links remain."""
    if not identity_id:
        return
    ident = store.get_external_identity(identity_id)
    if ident is None:
        return
    still = False
    entity_id = None
    for link in store.list_identity_links():
        st = getattr(link.status, "value", link.status)
        if st != IdentityStatus.confirmed.value:
            continue
        if identity_id in (link.left_identity_id, link.right_identity_id):
            still = True
            entity_id = link.entity_id or entity_id
            break
    if still:
        ident.confirmed = True
        if entity_id:
            ident.linked_entity_id = entity_id
        store.update_external_identity(ident)
        return
    if ident.confirmed or ident.linked_entity_id:
        ident.confirmed = False
        ident.linked_entity_id = None
        store.update_external_identity(ident)


def confirm_identity_link(
    store,
    link_id: str,
    *,
    entity_id: Optional[str] = None,
    allow_cross_domain: bool = False,
) -> IdentityLink:
    link = store.get_identity_link(link_id)
    if link is None:
        raise ValueError(f"identity link {link_id} not found")
    left = store.get_external_identity(link.left_identity_id)
    right = (
        store.get_external_identity(link.right_identity_id)
        if link.right_identity_id else None
    )
    if left and right:
        lv = left.vault_id or "vault_unknown"
        rv = right.vault_id or "vault_unknown"
        if lv != rv and not allow_cross_domain:
            raise ValueError(
                f"cross-vault identity confirmation refused "
                f"({lv} vs {rv}); pass allow_cross_domain=True"
            )
        if lv != rv:
            link.cross_domain = True
    link.status = IdentityStatus.confirmed
    link.confidence = max(link.confidence, 0.99)
    if entity_id:
        link.entity_id = entity_id
    store.update_identity_link(link)
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


def unconfirm_identity_link(store, link_id: str) -> IdentityLink:
    """Roll confirmation back to candidate (manual undo)."""
    link = store.get_identity_link(link_id)
    if link is None:
        raise ValueError(f"identity link {link_id} not found")
    link.status = IdentityStatus.candidate
    meta = dict(link.metadata or {})
    meta["unconfirmed_from"] = IdentityStatus.confirmed.value
    link.metadata = meta
    store.update_identity_link(link)
    _refresh_identity_confirmation(store, link.left_identity_id)
    _refresh_identity_confirmation(store, link.right_identity_id)
    return link


def reject_identity_link(store, link_id: str) -> IdentityLink:
    """Explicit negative decision — not auto-proposed again as confirmed."""
    link = store.get_identity_link(link_id)
    if link is None:
        raise ValueError(f"identity link {link_id} not found")
    link.status = IdentityStatus.rejected
    store.update_identity_link(link)
    _refresh_identity_confirmation(store, link.left_identity_id)
    _refresh_identity_confirmation(store, link.right_identity_id)
    return link


def ingest_actors_from_record(
    store, record: Any,
) -> list[ExternalIdentity]:
    """Upsert identities from a ConnectorRecord's actor/participant ids."""
    out: list[ExternalIdentity] = []
    account_id = getattr(record, "source_account_id", "") or ""
    meta = account_meta(store, record)
    seen: set[str] = set()
    for aid in list(getattr(record, "actor_ids", None) or []) + list(
        getattr(record, "participant_ids", None) or []
    ):
        if not aid or aid in seen:
            continue
        seen.add(aid)
        ident = upsert_external_identity(
            store, actor_id=aid, source_account_id=account_id,
            vault_id=meta["vault_id"],
            source_owner=meta["source_owner"],
            mapping_signals=["connector_record"],
        )
        if ident:
            out.append(ident)
    return out
