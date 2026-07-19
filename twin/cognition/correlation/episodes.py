"""WorkEpisode correlation across connectors (v0.6 Phase 7 §19).

Partitioned by vault. Merge anchors form clusters; contextual anchors
(fingerprint / thread) attach or form candidate-only episodes without
transitive overmerge. Episodes are idempotent via ``correlation_key`` and
reconciled so removed/tombstoned members leave active membership.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ...clock import now_iso
from .independence import evidence_directness_for, independence_group_for
from .models import (
    EpisodeLink,
    EpisodeLinkKind,
    EpisodeLinkStatus,
    EpisodeStatus,
    WorkEpisode,
)
from .partition import qualify_anchor, vault_for_record
from .projects import resolve_project_for_record

EPISODE_MERGE_CONFIDENCE = 0.75

# Anchors that may union components (episode identity).
_MERGE_KINDS = frozenset({
    EpisodeLinkKind.explicit,
    EpisodeLinkKind.reference,
    EpisodeLinkKind.derived,
})
# Attach / candidate-only — never fuse two distinct merge components.
_CONTEXTUAL_KINDS = frozenset({
    EpisodeLinkKind.fingerprint,
    EpisodeLinkKind.thread,
})

_REPO_PR = re.compile(
    r"github\.com/([\w.-]+/[\w.-]+)/(?:pull|issues)/(\d+)",
    re.I,
)
_LABELED_NUM = re.compile(r"\b(?:PR|pr|issue|Issue)\s*#(\d+)\b")

_ANCHOR_PRIORITY = (
    "lineage", "calendar_event_id", "iCalUID", "fingerprint", "thread",
)


def extract_github_refs(text: str, *, default_repo: Optional[str] = None) -> list[str]:
    """Return lineage-root style keys like ``github:org/repo#42``."""
    out: list[str] = []
    for m in _REPO_PR.finditer(text or ""):
        key = f"github:{m.group(1)}#{m.group(2)}"
        if key not in out:
            out.append(key)
    if default_repo:
        for m in _LABELED_NUM.finditer(text or ""):
            key = f"github:{default_repo}#{m.group(1)}"
            if key not in out:
                out.append(key)
    return out


class _UF:
    def __init__(self) -> None:
        self.parent: dict[str, str] = {}

    def add(self, x: str) -> None:
        self.parent.setdefault(x, x)

    def find(self, x: str) -> str:
        self.add(x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[rb] = ra


def _provider_for(record: Any) -> str:
    sm = getattr(record, "source_metadata", None) or {}
    if sm.get("provider"):
        return str(sm["provider"])
    # Infer from connector-ish metadata
    if sm.get("repo"):
        return "github"
    if sm.get("channel_id") or sm.get("team_id"):
        return "slack"
    et = getattr(record, "external_type", "") or ""
    if et.startswith("meeting") or "transcript" in et:
        return "fireflies"
    if "calendar" in et or sm.get("calendar_event_id"):
        return "calendar"
    return ""


def _record_anchors(
    record: Any, *, vault_id: str,
) -> list[tuple[str, str, EpisodeLinkKind, float, bool]]:
    """Return (anchor_type, qualified_key, kind, confidence, is_merge)."""
    out: list[tuple[str, str, EpisodeLinkKind, float, bool]] = []
    sm = getattr(record, "source_metadata", None) or {}
    account_id = getattr(record, "source_account_id", "") or ""
    provider = _provider_for(record)

    def _q(atype: str, value: str, *, acct: bool = False) -> str:
        return qualify_anchor(
            vault_id, atype, value,
            provider=provider,
            source_account_id=account_id if acct else "",
        )

    lineage = sm.get("lineage_root")
    if lineage:
        out.append((
            "lineage", _q("lineage", str(lineage)),
            EpisodeLinkKind.explicit, 0.95, True,
        ))
    note_of = sm.get("notification_of")
    if note_of:
        out.append((
            "lineage", _q("lineage", str(note_of)),
            EpisodeLinkKind.derived, 0.95, True,
        ))

    for field, kind, conf, merge, acct in (
        ("calendar_event_id", EpisodeLinkKind.explicit, 0.95, True, True),
        ("iCalUID", EpisodeLinkKind.explicit, 0.90, True, False),
    ):
        val = sm.get(field)
        if val:
            out.append((field, _q(field, str(val), acct=acct), kind, conf, merge))

    # Fingerprints are vault-scoped but provider-agnostic so calendar↔meeting
    # can match; they remain contextual (non-merge) anchors.
    fp = sm.get("correlation_fingerprint")
    if fp:
        out.append((
            "fingerprint",
            qualify_anchor(vault_id, "fingerprint", str(fp)),
            EpisodeLinkKind.fingerprint, 0.85, False,
        ))

    thread = getattr(record, "thread_key", None)
    if thread:
        # Threads are contextual — attach only, never fuse merge components.
        out.append((
            "thread", _q("thread", str(thread)),
            EpisodeLinkKind.thread, 0.80, False,
        ))

    content = getattr(record, "content", "") or ""
    repo = sm.get("repo")
    for ref in extract_github_refs(content, default_repo=repo):
        out.append((
            "lineage", _q("lineage", ref),
            EpisodeLinkKind.reference, 0.88, True,
        ))
    return out


def _source_ref(record: Any, *, vault_id: str) -> dict[str, Any]:
    sm = getattr(record, "source_metadata", None) or {}
    meta = {
        "external_id": getattr(record, "external_id", None),
        "thread_key": getattr(record, "thread_key", None),
        "source_metadata": sm,
        "artifact_refs": getattr(record, "artifact_refs", None) or [],
    }
    return {
        "connector_record_id": getattr(record, "id", None),
        "connector_id": getattr(record, "connector_id", None),
        "source_account_id": getattr(record, "source_account_id", None),
        "external_type": getattr(record, "external_type", None),
        "external_id": getattr(record, "external_id", None),
        "thread_key": getattr(record, "thread_key", None),
        "lineage_root": sm.get("lineage_root"),
        "occurred_at": getattr(record, "occurred_at", None),
        "project_hint": getattr(record, "project_hint", None),
        "vault_id": vault_id,
        "independence_group": independence_group_for(meta),
        "directness": evidence_directness_for(meta),
    }


def _correlation_key(vault_id: str, anchors: list[tuple[str, str, EpisodeLinkKind, float, bool]]) -> str:
    """Stable canonical key: prefer merge anchors by priority, else contextual."""
    by_type: dict[str, list[str]] = {}
    for atype, qkey, _kind, _conf, is_merge in anchors:
        if is_merge or atype in ("fingerprint", "thread"):
            by_type.setdefault(atype, []).append(qkey)
    for atype in _ANCHOR_PRIORITY:
        if atype in by_type:
            return sorted(by_type[atype])[0]
    # fallback — should not happen for multi-member clusters
    return f"{vault_id}:cluster:{sorted(a[1] for a in anchors)[0] if anchors else 'empty'}"


def _episode_title(members: list[Any]) -> str:
    for rec in members:
        content = (getattr(rec, "content", None) or "").strip()
        if content:
            line = content.splitlines()[0].lstrip("# ").strip()
            if line:
                return line[:120]
        hint = getattr(rec, "project_hint", None)
        if hint:
            return f"Work on {hint}"
    return "Work episode"


def _rebuild_episode_from_active_links(store, ep: WorkEpisode) -> WorkEpisode:
    """Recompute aggregates from active EpisodeLinks only."""
    links = [
        lk for lk in store.list_episode_links(ep.id)
        if lk.status == EpisodeLinkStatus.active
        or getattr(lk.status, "value", lk.status) == "active"
    ]
    refs: list[dict[str, Any]] = []
    actors: list[str] = []
    times: list[str] = []
    groups: set[str] = set()
    for lk in links:
        ref = {
            "connector_record_id": lk.connector_record_id,
            "external_type": lk.external_type,
            "external_id": lk.external_id,
            "thread_key": lk.thread_key,
            "lineage_root": lk.lineage_root,
            "vault_id": lk.vault_id or ep.vault_id,
            "independence_group": lk.independence_group,
            "directness": lk.directness,
        }
        if lk.connector_record_id and hasattr(store, "get_connector_record"):
            rec = store.get_connector_record(lk.connector_record_id)
            if rec is not None:
                ref["occurred_at"] = rec.occurred_at
                ref["connector_id"] = rec.connector_id
                ref["source_account_id"] = rec.source_account_id
                ref["project_hint"] = rec.project_hint
                if rec.occurred_at:
                    times.append(rec.occurred_at)
                for a in list(rec.actor_ids or []) + list(rec.participant_ids or []):
                    if a and a not in actors:
                        actors.append(a)
        refs.append(ref)
        if lk.independence_group:
            groups.add(lk.independence_group)

    ep.source_refs = refs
    ep.participant_actor_ids = actors
    times_sorted = sorted(times)
    ep.started_at = times_sorted[0] if times_sorted else None
    ep.ended_at = times_sorted[-1] if times_sorted else None
    ep.independence_group_count = len(groups)
    # Keep primary lineage if still present among active links.
    lineage_groups = sorted(g for g in groups if g.startswith("lineage:"))
    ep.independence_group = lineage_groups[0] if lineage_groups else None
    if not links:
        ep.status = EpisodeStatus.closed
    ep.updated_at = now_iso()
    store.update_work_episode(ep)
    return ep


def _upsert_anchor(store, *, episode_id: str, vault_id: str, atype: str, qkey: str) -> None:
    if hasattr(store, "upsert_episode_anchor"):
        store.upsert_episode_anchor(
            episode_id=episode_id, vault_id=vault_id,
            anchor_type=atype, anchor_value=qkey,
        )


def _find_existing_episode(
    store, *, vault_id: str, correlation_key: str,
    anchors: list[tuple[str, str, EpisodeLinkKind, float, bool]],
) -> Optional[WorkEpisode]:
    if hasattr(store, "find_work_episode_by_correlation_key"):
        ep = store.find_work_episode_by_correlation_key(vault_id, correlation_key)
        if ep:
            return ep
    for atype, qkey, _k, _c, _m in anchors:
        if hasattr(store, "find_work_episode_by_anchor"):
            ep = store.find_work_episode_by_anchor(vault_id, atype, qkey)
            if ep:
                return ep
    # Legacy lineage lookup scoped by vault
    for atype, qkey, _k, _c, _m in anchors:
        if atype == "lineage" and hasattr(store, "find_work_episode_by_lineage"):
            # qkey is vault:lineage:provider?:value — extract bare lineage for legacy
            bare = qkey.split("lineage:", 1)[-1]
            # strip optional provider prefix if present as account-less form
            ep = store.find_work_episode_by_lineage(bare, vault_id=vault_id)
            if ep:
                return ep
    return None


def _sync_membership(
    store,
    ep: WorkEpisode,
    members: list[Any],
    *,
    vault_id: str,
    anchors_by_record: dict[str, list],
    deleted_record_ids: set[str],
) -> None:
    """Set active links for members; remove links for non-members / tombstones."""
    desired: dict[tuple[str, str], Any] = {}
    for rec in members:
        key = (
            str(getattr(rec, "external_type", "") or ""),
            str(getattr(rec, "external_id", "") or ""),
        )
        desired[key] = rec

    existing = store.list_episode_links(ep.id)
    for lk in existing:
        key = (lk.external_type, lk.external_id)
        rid = lk.connector_record_id
        keep = key in desired
        if rid and rid in deleted_record_ids:
            keep = False
        if keep:
            rec = desired[key]
            sm = getattr(rec, "source_metadata", None) or {}
            meta = {
                "external_id": rec.external_id,
                "thread_key": rec.thread_key,
                "source_metadata": sm,
                "artifact_refs": getattr(rec, "artifact_refs", None) or [],
            }
            best_kind = EpisodeLinkKind.soft
            best_conf = 0.4
            for _atype, _qkey, kind, conf, _m in anchors_by_record.get(rec.id, []):
                if conf > best_conf:
                    best_conf, best_kind = conf, kind
            lk.status = EpisodeLinkStatus.active
            lk.connector_record_id = rec.id
            lk.kind = best_kind
            lk.confidence = best_conf
            lk.independence_group = independence_group_for(meta)
            lk.directness = evidence_directness_for(meta)
            lk.lineage_root = sm.get("lineage_root")
            lk.thread_key = rec.thread_key
            lk.vault_id = vault_id
            lk.updated_at = now_iso()
            store.update_episode_link(lk)
            del desired[key]
        else:
            if lk.status != EpisodeLinkStatus.removed:
                lk.status = EpisodeLinkStatus.removed
                lk.updated_at = now_iso()
                store.update_episode_link(lk)

    for rec in desired.values():
        sm = getattr(rec, "source_metadata", None) or {}
        meta = {
            "external_id": rec.external_id,
            "thread_key": rec.thread_key,
            "source_metadata": sm,
            "artifact_refs": getattr(rec, "artifact_refs", None) or [],
        }
        best_kind = EpisodeLinkKind.soft
        best_conf = 0.4
        for _atype, _qkey, kind, conf, _m in anchors_by_record.get(rec.id, []):
            if conf > best_conf:
                best_conf, best_kind = conf, kind
        prior = store.find_episode_link(
            ep.id, rec.external_type, rec.external_id,
        )
        if prior is not None:
            prior.status = EpisodeLinkStatus.active
            prior.connector_record_id = rec.id
            prior.kind = best_kind
            prior.confidence = best_conf
            prior.independence_group = independence_group_for(meta)
            prior.directness = evidence_directness_for(meta)
            prior.vault_id = vault_id
            prior.updated_at = now_iso()
            store.update_episode_link(prior)
            continue
        link = EpisodeLink(
            episode_id=ep.id,
            vault_id=vault_id,
            connector_record_id=rec.id,
            external_type=rec.external_type or "",
            external_id=rec.external_id or "",
            thread_key=rec.thread_key,
            lineage_root=sm.get("lineage_root"),
            kind=best_kind,
            status=EpisodeLinkStatus.active,
            independence_group=independence_group_for(meta),
            directness=evidence_directness_for(meta),
            confidence=best_conf,
        )
        store.insert_episode_link(link)


def correlate_records(
    store,
    records: list[Any],
    *,
    vault_id: Optional[str] = None,
    min_confidence: float = EPISODE_MERGE_CONFIDENCE,
    create_singletons: bool = False,
    deleted_record_ids: Optional[set[str]] = None,
) -> list[WorkEpisode]:
    """Cluster connector records into WorkEpisodes within one vault.

    ``vault_id`` is required for multi-record correlation. When omitted, it is
    inferred from the first record (single-vault call sites only).
    """
    deleted_record_ids = deleted_record_ids or set()
    if not records:
        if not deleted_record_ids or not vault_id:
            return []
        # Tombstone-only reconciliation for this vault.
        episodes: list[WorkEpisode] = []
        if hasattr(store, "list_work_episodes"):
            for ep in store.list_work_episodes(vault_id=vault_id, limit=500):
                changed = False
                for lk in store.list_episode_links(ep.id):
                    if (
                        lk.connector_record_id in deleted_record_ids
                        and lk.status != EpisodeLinkStatus.removed
                    ):
                        lk.status = EpisodeLinkStatus.removed
                        lk.updated_at = now_iso()
                        store.update_episode_link(lk)
                        changed = True
                if changed:
                    episodes.append(_rebuild_episode_from_active_links(store, ep))
        return episodes

    if vault_id is None:
        vault_id = vault_for_record(store, records[0])
    # Refuse silent cross-vault mixing inside one call.
    for rec in records:
        if vault_for_record(store, rec) != vault_id:
            raise ValueError(
                "correlate_records received records from multiple vaults; "
                "partition first"
            )

    record_by_id: dict[str, Any] = {}
    anchors_by_record: dict[str, list] = {}
    for rec in records:
        rid = getattr(rec, "id", None)
        if not rid:
            continue
        record_by_id[rid] = rec
        anchors_by_record[rid] = _record_anchors(rec, vault_id=vault_id)

    # --- Merge UF (episode-identity anchors only) ---
    uf = _UF()
    merge_owners: dict[str, list[str]] = {}
    for rid, anchors in anchors_by_record.items():
        merge_keys = [q for _t, q, _k, c, m in anchors if m and c >= min_confidence]
        for i, ka in enumerate(merge_keys):
            uf.add(ka)
            for kb in merge_keys[i + 1:]:
                uf.union(ka, kb)
            merge_owners.setdefault(ka, []).append(rid)

    merge_components: dict[str, set[str]] = {}
    for key, owners in merge_owners.items():
        root = uf.find(key)
        merge_components.setdefault(root, set()).update(owners)

    # Map record → merge component root (if any)
    record_merge_root: dict[str, str] = {}
    for root, members in merge_components.items():
        for rid in members:
            record_merge_root[rid] = root

    # --- Contextual fingerprint clusters (candidate episodes) ---
    fp_groups: dict[str, set[str]] = {}
    thread_groups: dict[str, set[str]] = {}
    for rid, anchors in anchors_by_record.items():
        for atype, qkey, _k, _c, is_merge in anchors:
            if atype == "fingerprint" and not is_merge:
                fp_groups.setdefault(qkey, set()).add(rid)
            if atype == "thread" and not is_merge:
                thread_groups.setdefault(qkey, set()).add(rid)

    # Attach contextual-only records to an existing merge component when they
    # share a thread/fingerprint with a merge member — without fusing two merges.
    for group in list(fp_groups.values()) + list(thread_groups.values()):
        merge_roots = {
            record_merge_root[r] for r in group if r in record_merge_root
        }
        if len(merge_roots) == 1:
            root = next(iter(merge_roots))
            for rid in group:
                if rid not in record_merge_root:
                    merge_components[root].add(rid)
                    record_merge_root[rid] = root
        # If 0 merge roots and size>=2 → candidate cluster from fingerprint/thread
        # If 2+ merge roots → do NOT union (avoid transitive overmerge)

    clusters: list[set[str]] = list(merge_components.values())
    # Fingerprint-only candidate clusters
    for qkey, group in fp_groups.items():
        if len(group) < 2:
            continue
        if any(r in record_merge_root for r in group):
            continue  # already attached
        clusters.append(set(group))

    episodes: list[WorkEpisode] = []
    touched_episode_ids: set[str] = set()

    for member_ids in clusters:
        members = [record_by_id[r] for r in member_ids if r in record_by_id]
        if len(members) < 2 and not create_singletons:
            continue

        # Collect anchors across members
        all_anchors: list[tuple[str, str, EpisodeLinkKind, float, bool]] = []
        for rid in member_ids:
            all_anchors.extend(anchors_by_record.get(rid, []))

        merge_anchors = [a for a in all_anchors if a[4]]
        conf = max((c for _t, _q, _k, c, m in all_anchors if m or _t == "fingerprint"), default=0.0)
        if conf < min_confidence and not create_singletons:
            # Allow fingerprint-only candidate clusters at 0.85
            if not any(a[0] == "fingerprint" for a in all_anchors):
                continue

        corr_key = _correlation_key(vault_id, all_anchors)
        existing = _find_existing_episode(
            store, vault_id=vault_id, correlation_key=corr_key,
            anchors=all_anchors,
        )

        project_id = None
        for rec in members:
            pid, _ = resolve_project_for_record(store, rec)
            if pid:
                project_id = pid
                break

        has_merge = bool(merge_anchors)
        status = (
            EpisodeStatus.active if has_merge and conf >= 0.90
            else EpisodeStatus.candidate
        )
        lineage_keys = [
            q for t, q, _k, _c, m in all_anchors if t == "lineage" and m
        ]
        primary_indep = None
        if lineage_keys:
            # Store bare lineage for human readability; partition is vault_id.
            bare = lineage_keys[0].split("lineage:", 1)[-1]
            # strip provider/account qualification if present: keep last github:…#N
            if "github:" in bare:
                bare = "github:" + bare.split("github:", 1)[-1]
            primary_indep = f"lineage:{bare}"

        title = _episode_title(members)
        if existing is None:
            ep = WorkEpisode(
                vault_id=vault_id,
                correlation_key=corr_key,
                project_id=project_id,
                title=title,
                status=status,
                independence_group=primary_indep,
                confidence=conf,
                metadata={
                    "link_kinds": sorted({k.value for _t, _q, k, _c, _m in all_anchors}),
                },
            )
            store.insert_work_episode(ep)
        else:
            ep = existing
            # Refuse cross-vault reuse
            if ep.vault_id and ep.vault_id != vault_id:
                continue
            ep.vault_id = vault_id
            ep.correlation_key = ep.correlation_key or corr_key
            ep.title = ep.title or title
            ep.project_id = ep.project_id or project_id
            ep.confidence = max(ep.confidence, conf)
            if status == EpisodeStatus.active and ep.status == EpisodeStatus.candidate:
                ep.status = EpisodeStatus.active
            if ep.status == EpisodeStatus.closed and members:
                ep.status = status
            ep.updated_at = now_iso()
            store.update_work_episode(ep)

        for atype, qkey, _k, _c, _m in all_anchors:
            _upsert_anchor(
                store, episode_id=ep.id, vault_id=vault_id,
                atype=atype, qkey=qkey,
            )

        _sync_membership(
            store, ep, members,
            vault_id=vault_id,
            anchors_by_record=anchors_by_record,
            deleted_record_ids=deleted_record_ids,
        )
        ep = _rebuild_episode_from_active_links(store, ep)
        touched_episode_ids.add(ep.id)
        episodes.append(ep)

    # Reconcile: remove membership for tombstoned records on any vault episode
    if deleted_record_ids and hasattr(store, "list_work_episodes"):
        for ep in store.list_work_episodes(vault_id=vault_id, limit=500):
            changed = False
            for lk in store.list_episode_links(ep.id):
                if (
                    lk.connector_record_id in deleted_record_ids
                    and lk.status != EpisodeLinkStatus.removed
                ):
                    lk.status = EpisodeLinkStatus.removed
                    lk.updated_at = now_iso()
                    store.update_episode_link(lk)
                    changed = True
            if changed:
                ep = _rebuild_episode_from_active_links(store, ep)
                if ep.id not in touched_episode_ids:
                    episodes.append(ep)

    return episodes
