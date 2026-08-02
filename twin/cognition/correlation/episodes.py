"""WorkEpisode correlation across connectors.

Partitioned by vault. Merge anchors form clusters; contextual anchors
(fingerprint / thread) attach or form candidate-only episodes without
transitive overmerge. Episodes are idempotent via ``correlation_key`` and
reconciled so removed/tombstoned members leave active membership.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from ...clock import now_iso

log = logging.getLogger(__name__)
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

# Soft-fuse (cross-sense): stricter than ACC scoring. Never fuse on
# project+time alone — requires distinctive lexical overlap.
SOFT_FUSE_WINDOW_DAYS = 7
SOFT_FUSE_MIN_SHARED_TOKENS = 2
SOFT_FUSE_MIN_LEX_RATIO = 0.15

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
# High-precision PR/issue references that tie a commit to its pull request.
# Covers the forms Git/GitHub actually produce so a merged PR and its landing
# commit end up in the same episode component:
#   - "PR #8" / "issue #8"            (explicit label)
#   - "Merge pull request #8 from …"  (default merge-commit subject)
#   - "… fix the thing (#8)"          (default squash-merge subject suffix)
#   - "closes/fixes/resolves #8"      (closing keywords)
_LABELED_NUM = re.compile(
    r"\b(?:"
    r"prs?|issues?|"
    r"pull\s+request|"
    r"close[sd]?|closed|"
    r"fix(?:e[sd])?|"
    r"resolve[sd]?"
    r")\s*#(\d+)\b",
    re.I,
)
# The GitHub squash-merge default appends "(#N)" to the commit subject.
_SQUASH_NUM = re.compile(r"\(#(\d+)\)")

_ANCHOR_PRIORITY = (
    "lineage", "calendar_event_id", "iCalUID", "fingerprint", "thread",
)


def extract_github_refs(text: str, *, default_repo: Optional[str] = None) -> list[str]:
    """Return lineage-root style keys like ``github:org/repo#42``.

    Recognizes full ``github.com/org/repo/pull/N`` URLs plus the labelled,
    merge-commit, squash-merge and closing-keyword forms that reference a PR in
    the record's own repo (``default_repo``). This is what links a landing
    commit to its PR so the pair forms a two-phase episode.
    """
    out: list[str] = []
    for m in _REPO_PR.finditer(text or ""):
        key = f"github:{m.group(1)}#{m.group(2)}"
        if key not in out:
            out.append(key)
    if default_repo:
        for pattern in (_LABELED_NUM, _SQUASH_NUM):
            for m in pattern.finditer(text or ""):
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

    # Authoritative PR ↔ landing-commit link: a merged PR's ``merge_commit_sha``
    # equals the sha of the commit record (its ``external_id``). Both sides emit
    # the same ``commit_sha`` anchor, so they fuse structurally — no dependence
    # on commit-message conventions. (Two records with the same sha, e.g. the
    # same commit seen by two connector instances, also dedupe here.)
    merge_sha = sm.get("merge_commit_sha")
    if merge_sha:
        out.append((
            "commit_sha", _q("commit_sha", str(merge_sha)),
            EpisodeLinkKind.explicit, 0.95, True,
        ))
    if provider == "github" and getattr(record, "external_type", "") == "commit":
        sha = getattr(record, "external_id", "") or ""
        if sha:
            out.append((
                "commit_sha", _q("commit_sha", str(sha)),
                EpisodeLinkKind.derived, 0.9, True,
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


_PR_LINEAGE = re.compile(r"github:[\w.-]+/[\w.-]+#\d+")


def _has_pr_lineage_merge(
    member_ids: set[str],
    anchors_by_record: dict[str, list],
) -> bool:
    """True when a component carries a merge-grade ``github:org/repo#N`` anchor.

    A lone ``Merge pull request #N`` commit must open an episode even before the
    ``pull_request`` API object has been synced.
    """
    for rid in member_ids:
        for atype, qkey, _k, _c, is_merge in anchors_by_record.get(rid, []):
            if atype == "lineage" and is_merge and _PR_LINEAGE.search(qkey or ""):
                return True
    return False


def _soft_fuse_cross_sense(
    store,
    record_by_id: dict[str, Any],
    clusters: list[set[str]],
    *,
    vault_id: str,
) -> list[set[str]]:
    """Conservatively union Slack↔GitHub components that share project + topic.

    Never unions two distinct GitHub merge components. Orphan records (not yet
    in a cluster) participate as singleton candidates so a Slack request can
    join a PR episode opened by a merge-commit.
    """
    from .. import sense_lenses
    from .text import normalize_for_compare

    stop = frozenset(
        "the a an and or of to in on for with from into is are was were be "
        "this that it its as at by we i you he she they them our your will "
        "would should could can may not no do does did have has had but if "
        "then so about slack message channel by commit merge pull request "
        "github state merged closed feat fix docs what needs order enter "
        "version launched implemented".split()
    )

    def _tokens(text: str) -> set[str]:
        raw = normalize_for_compare(text or "")
        out: set[str] = set()
        for t in raw.split():
            if len(t) < 3 or t in stop:
                continue
            # Drop Slack/GitHub opaque ids and short shas — they inflate
            # denominators and never help topic matching.
            if t.startswith(("c0", "u0", "w0", "t0")) and any(ch.isdigit() for ch in t):
                continue
            if len(t) >= 7 and all(c in "0123456789abcdef" for c in t):
                continue
            out.add(t)
        return out

    def _sense(rec: Any) -> str:
        return sense_lenses.sense_for_record(rec)

    def _project(rec: Any) -> Optional[str]:
        pid, _ = resolve_project_for_record(store, rec)
        return pid

    def _when(rec: Any) -> Optional[str]:
        return getattr(rec, "occurred_at", None)

    def _parse(ts: Optional[str]):
        if not ts:
            return None
        try:
            from datetime import datetime, timezone
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(
                timezone.utc
            )
        except Exception:
            return None

    clustered: set[str] = set()
    for c in clusters:
        clustered |= c
    components: list[set[str]] = [set(c) for c in clusters if c]
    for rid in record_by_id:
        if rid not in clustered:
            components.append({rid})

    if len(components) < 2:
        return [c for c in components if len(c) >= 2] or clusters

    # Precompute per-component summaries
    meta: list[dict[str, Any]] = []
    for comp in components:
        recs = [record_by_id[r] for r in comp if r in record_by_id]
        senses = {_sense(r) for r in recs}
        projects = {p for p in (_project(r) for r in recs) if p}
        tokens: set[str] = set()
        times = []
        for r in recs:
            tokens |= _tokens(getattr(r, "content", "") or "")
            t = _parse(_when(r))
            if t is not None:
                times.append(t)
        # github_refs in slack metadata count as explicit preference
        gh_refs: set[str] = set()
        for r in recs:
            sm = getattr(r, "source_metadata", None) or {}
            for ref in sm.get("github_refs") or []:
                if isinstance(ref, dict) and ref.get("repo") and ref.get("number"):
                    gh_refs.add(f"{ref['repo']}#{ref['number']}")
                elif isinstance(ref, str):
                    gh_refs.add(ref)
        has_pr = any(
            getattr(r, "external_type", "") == "pull_request"
            or (
                getattr(r, "external_type", "") == "commit"
                and "pull request #" in (getattr(r, "content", "") or "").lower()
            )
            for r in recs
        )
        meta.append({
            "senses": senses,
            "projects": projects,
            "tokens": tokens,
            "t_min": min(times) if times else None,
            "t_max": max(times) if times else None,
            "gh_refs": gh_refs,
            "has_github": "github" in senses,
            "has_slack": "slack" in senses,
            "has_pr": has_pr,
        })

    from datetime import timedelta
    window = timedelta(days=SOFT_FUSE_WINDOW_DAYS)

    def _pair_ok(si: int, gi: int) -> tuple[bool, float]:
        """Return (matches, score) for attaching slack component → github."""
        a, b = meta[si], meta[gi]
        if not (a["projects"] & b["projects"]):
            return False, 0.0
        if a["t_min"] is None or b["t_min"] is None:
            return False, 0.0
        earlier_end = min(a["t_max"], b["t_max"])
        later_start = max(a["t_min"], b["t_min"])
        if later_start - earlier_end > window:
            return False, 0.0
        shared = a["tokens"] & b["tokens"]
        explicit = False
        for ref in a["gh_refs"]:
            num = ref.split("#")[-1] if "#" in ref else ""
            if num and any(
                num in (getattr(record_by_id[r], "external_id", "") or "")
                for r in components[gi]
            ):
                explicit = True
                break
        ratio = len(shared) / max(1, min(len(a["tokens"]), len(b["tokens"])))
        if not explicit and (
            len(shared) < SOFT_FUSE_MIN_SHARED_TOKENS
            or ratio < SOFT_FUSE_MIN_LEX_RATIO
        ):
            return False, 0.0
        # Prefer explicit PR refs, denser lexical overlap, then temporal
        # proximity (request ↔ merge) so a follow-up harden PR does not beat
        # the PR that landed minutes before the Slack ask.
        a_mid = a["t_min"] + (a["t_max"] - a["t_min"]) / 2
        b_mid = b["t_min"] + (b["t_max"] - b["t_min"]) / 2
        hours_apart = abs((a_mid - b_mid).total_seconds()) / 3600.0
        score = (
            (10.0 if explicit else 0.0)
            + len(shared)
            + ratio
            + 3.0 / (1.0 + hours_apart)
        )
        return True, score

    # Attach each Slack-only component to exactly one best GitHub target.
    # Never union two GitHub merge components through a Slack hub.
    sl_idxs = [
        i for i, m in enumerate(meta)
        if m["has_slack"] and not m["has_github"]
    ]
    # Only attach onto components that already represent a PR (record or
    # merge-commit). Random historical commits that happen to share words
    # like "presets" must not steal the Slack request.
    gh_idxs = [
        i for i, m in enumerate(meta)
        if m["has_github"] and not m["has_slack"] and m["has_pr"]
    ]
    attach: dict[int, int] = {}  # slack_idx → github_idx
    for si in sl_idxs:
        best: Optional[tuple[float, int]] = None
        for gi in gh_idxs:
            ok, score = _pair_ok(si, gi)
            if not ok:
                continue
            # Prefer components that contain a pull_request record.
            if any(
                getattr(record_by_id[r], "external_type", "") == "pull_request"
                for r in components[gi]
            ):
                score += 2.0
            if best is None or score > best[0]:
                best = (score, gi)
        if best is not None:
            attach[si] = best[1]

    fused: dict[int, set[str]] = {}
    claimed_slack: set[int] = set()
    for gi in gh_idxs:
        bucket = set(components[gi])
        for si, target in attach.items():
            if target == gi:
                bucket |= components[si]
                claimed_slack.add(si)
        fused[gi] = bucket
    # Slack that didn't attach stays as its own component (usually dropped
    # unless multi-member); preserve mixed components already in input.
    for i, comp in enumerate(components):
        if i in gh_idxs or i in claimed_slack:
            continue
        if meta[i]["has_slack"] and meta[i]["has_github"]:
            fused[i] = set(comp)
        elif len(comp) >= 2:
            fused[i] = set(comp)

    out = [c for c in fused.values() if len(c) >= 2]
    # Keep explicit singletons that were passed in (e.g. PR-lineage merge
    # commits) when they were not absorbed into a multi-member fuse.
    absorbed: set[str] = set().union(*out) if out else set()
    for c in clusters:
        if len(c) == 1 and c.isdisjoint(absorbed):
            out.append(set(c))
    return out or clusters


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
    # Confidence follows active membership — shrink/downgrade when evidence
    # leaves.
    # ``closed`` here means "no active members" and is reversible on rebuild
    # when evidence returns (not a permanent manual close).
    if links:
        ep.confidence = max(float(lk.confidence or 0.0) for lk in links)
        if ep.status == EpisodeStatus.closed or (
            getattr(ep.status, "value", ep.status) == EpisodeStatus.closed.value
        ):
            ep.status = EpisodeStatus.candidate
    else:
        ep.confidence = 0.0
        ep.status = EpisodeStatus.closed
    ep.updated_at = now_iso()
    store.update_work_episode(ep)
    # Sensory scaffold stops at structural membership. The semantic arc
    # (phases → narrative edges) is built by the cortex cognition stage
    # (LLM), not here — correlation never invents an arc from lexical rules.
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
    """Resolve an existing episode by its canonical correlation key only.

    Looking up by *any* secondary anchor is unsafe after soft-fuse / re-runs:
    an episode can accumulate stale anchors from a prior over-merge, and a
    later cluster that shares one of those anchors would steal membership
    (wiping the real members via ``_sync_membership``).
    """
    if hasattr(store, "find_work_episode_by_correlation_key"):
        ep = store.find_work_episode_by_correlation_key(vault_id, correlation_key)
        if ep:
            return ep
    # Legacy: only when the correlation key itself is a lineage key.
    if ":lineage:" in (correlation_key or "") and hasattr(
        store, "find_work_episode_by_lineage"
    ):
        bare = correlation_key.split("lineage:", 1)[-1]
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

    # A merge-commit referencing PR #N opens an episode even without the
    # pull_request record (soft-fuse can then attach Slack into it).
    clustered_ids: set[str] = set().union(*clusters) if clusters else set()
    for rid in record_by_id:
        if rid in clustered_ids:
            continue
        if _has_pr_lineage_merge({rid}, anchors_by_record):
            clusters.append({rid})
            clustered_ids.add(rid)

    clusters = _soft_fuse_cross_sense(
        store, record_by_id, clusters, vault_id=vault_id,
    )

    episodes: list[WorkEpisode] = []
    touched_episode_ids: set[str] = set()

    for member_ids in clusters:
        members = [record_by_id[r] for r in member_ids if r in record_by_id]
        allow_singleton = _has_pr_lineage_merge(member_ids, anchors_by_record)
        if len(members) < 2 and not create_singletons and not allow_singleton:
            continue

        # Collect anchors across members
        all_anchors: list[tuple[str, str, EpisodeLinkKind, float, bool]] = []
        for rid in member_ids:
            all_anchors.extend(anchors_by_record.get(rid, []))

        merge_anchors = [a for a in all_anchors if a[4]]
        conf = max((c for _t, _q, _k, c, m in all_anchors if m or _t == "fingerprint"), default=0.0)
        if conf < min_confidence and not create_singletons and not allow_singleton:
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
        from .. import sense_lenses
        senses = sorted({sense_lenses.sense_for_record(r) for r in members})
        cross_sense = len(senses) >= 2
        meta_base = {
            "link_kinds": sorted({k.value for _t, _q, k, _c, _m in all_anchors}),
            "senses": senses,
            "cross_sense_soft_fuse": cross_sense,
        }
        if existing is None:
            ep = WorkEpisode(
                vault_id=vault_id,
                correlation_key=corr_key,
                project_id=project_id,
                title=title,
                status=status,
                independence_group=primary_indep,
                confidence=conf,
                metadata=meta_base,
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
            ep.metadata = {**(ep.metadata or {}), **meta_base}
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
