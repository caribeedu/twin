"""Safe_context_pack — recall, packaged for external LLMs.

Given a task description and a target domain, returns a compact, firewall-
filtered context pack ready to prepend to an external LLM's prompt, with
sources and the list of blocked memories (ids + rule only, never content).

Only *confirmed* memories enter a pack by default — candidates must be
explicitly requested (``include_candidates=True``) and are tagged.

Packs are **task-aware**: a profile (coding, architecture, debugging,
writing, planning, review, meeting_prep) changes section ordering and token
allocation while preserving the same firewall and evidence guarantees.
Retrieval runs through the multi-stage pipeline (graph expansion, temporal
filtering, source-trust weighting, optional local reranking).

The evidence guarantee is enforced by construction: when the pack will
carry evidence quotes, their budget is reserved *before* memory sections
are packed, so filling the pack can never squeeze the evidence out. The
result reports ``evidence_included`` / ``evidence_omitted_due_to_budget``
explicitly. Budget a section does not use is redistributed in a second
pass over the best remaining hits.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from typing import Any, Optional

from ..config import Config
from twin.privacy.firewall import Firewall
from twin.cognize.stance_engine.profile import load_profile
from twin.store.embeddings import Embedder
from twin.store.search import SearchHit
from twin.store.store.base import TwinStore
from ..privacy.models import AccessRequest
from twin.inject.pack_format import PackMode, render_pack
from twin.inject.pack_select import (
    build_provenance_summary,
    cognitive_label,
    dedupe_and_diversify,
    prefer_current,
    project_goals,
    screen_injection,
)
from twin.cognize.services.retrieval import Reranker, retrieve
from twin.cognize.services.task_profiles import get_profile


class PackDeadlineExceeded(Exception):
    """Pack assembly aborted because a monotonic deadline was reached."""

    def __init__(self, stage: str = ""):
        self.stage = stage
        super().__init__(f"pack deadline exceeded at {stage or 'unknown'}")


def _check_pack_deadline(deadline_monotonic: Optional[float], *, stage: str) -> None:
    if deadline_monotonic is None:
        return
    if time.monotonic() >= deadline_monotonic:
        raise PackDeadlineExceeded(stage)

CHARS_PER_TOKEN = 4  # rough heuristic; packs are small so precision is not critical
EVIDENCE_LINE_CHARS = 260  # reserved per evidence quote (id + 220-char quote)


@dataclass
class ContextPack:
    context_pack: str
    sources: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    blocked: list[dict] = field(default_factory=list)
    task_profile: str = "general"
    project_id: Optional[str] = None
    judgment_snapshot_id: Optional[str] = None
    privacy_decision_id: Optional[str] = None
    privacy_meta: dict = field(default_factory=dict)
    # the evidence guarantee is explicit, never implied: callers see whether
    # quotes made it in and, if not, that the budget was the reason
    evidence_included: bool = False
    evidence_omitted_due_to_budget: bool = False
    mode: str = "compact"
    request_scope: str = ""
    active: dict = field(default_factory=dict)
    uncertainty: dict = field(default_factory=dict)
    provenance_summary: list = field(default_factory=list)
    token_budget: dict = field(default_factory=dict)
    blocked_count: int = 0
    explanation: dict = field(default_factory=dict)
    narratives: list = field(default_factory=list)
    open_reflections: list = field(default_factory=list)
    epistemic: list = field(default_factory=list)
    derived_confidence: dict = field(default_factory=dict)
    applicable_stance: list = field(default_factory=list)
    applicable_judgment: list = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _entry_from_view(
    view: dict, *, status: Optional[str] = None, label: str = "ok",
) -> str:
    title = view.get("title") or "[redacted]"
    summary = view.get("summary") or ""
    if view.get("redacted"):
        tag = "redacted"
    elif status == "candidate":
        tag = "candidate"
    else:
        tag = label or "ok"
    return f"- [{tag}] {title}: {summary}"


def _evidence_lines(store: TwinStore, hits: list[SearchHit], top_n: int,
                    *, skip_ids: Optional[set[str]] = None) -> list[str]:
    skip_ids = skip_ids or set()
    top = sorted(
        [h for h in hits if h.claim.id not in skip_ids],
        key=lambda h: h.score, reverse=True,
    )[:top_n]
    lines: list[str] = []
    for hit in top:
        for ev in store.get_evidence(hit.claim.id)[:1]:
            quote = ev.quote if len(ev.quote) <= 220 else ev.quote[:217] + "..."
            lines.append(f'- [{hit.claim.id}] "{quote}"')
    return lines


def build_context_pack(
    store: TwinStore,
    cfg: Config,
    embedder: Embedder,
    query: str,
    target_domain: str = "technical",
    max_tokens: int = 1200,
    include_judgment: bool = True,
    include_candidates: bool = False,
    task_profile: str = "general",
    project_id: Optional[str] = None,
    firewall: Optional[Firewall] = None,
    reranker: Optional[Reranker] = None,
    access: Optional[AccessRequest] = None,
    *,
    session_id: Optional[str] = None,
    mode: PackMode = "compact",
    request_scope: Optional[str] = None,
    deadline_monotonic: Optional[float] = None,
) -> ContextPack:
    firewall = firewall or Firewall(cfg.policies_path, store)
    profile = get_profile(task_profile)
    _check_pack_deadline(deadline_monotonic, stage="before_retrieve")
    result = retrieve(
        store, embedder, query,
        target_domain=target_domain, firewall=firewall, limit=25,
        include_candidates=include_candidates, project_id=project_id,
        reranker=reranker,
    )
    _check_pack_deadline(deadline_monotonic, stage="after_retrieve")

    # Missing identity → restricted mode (never elevate to local-cli).
    from ..privacy.identity import restricted_access
    access = access or restricted_access(
        project_id=project_id, requested_domains=[target_domain],
    )
    # Persona scope may have narrowed domains — never widen pack target.
    if access.requested_domains and target_domain not in access.requested_domains:
        if "*" not in access.requested_domains:
            target_domain = access.requested_domains[0]
    privacy_decision_id: Optional[str] = None
    privacy_meta: dict = {}
    privacy_blocked: list[dict] = []
    authorized_views: dict[str, dict] = {}
    redacted_ids: set[str] = set()
    if hasattr(store, "insert_privacy_decision"):
        from ..privacy.engine import evaluate_access
        memories = [h.claim for h in result.hits]
        ev = evaluate_access(
            store, access, memories,
            policies_path=cfg.policies_path,
            legacy_firewall=firewall,
            target_domain=target_domain,
            persist=True,
        )
        privacy_decision_id = ev["decision_id"]
        privacy_meta = {
            "privacy_decision_id": privacy_decision_id,
            "resources_considered": ev["decision"].metadata.get("resources_considered"),
            "resources_allowed": ev["decision"].metadata.get("resources_allowed"),
            "resources_redacted": ev["decision"].metadata.get("resources_redacted"),
            "resources_denied": ev["decision"].metadata.get("resources_denied"),
            "grant_ids": ev["decision"].grant_ids,
            "policy_set_version": ev.get("policy_set_version_id"),
            "obligations": ev.get("obligations") or [],
            "execution_location": ev.get("execution_location"),
        }
        privacy_blocked = list(ev["denied"])
        for v in ev["allowed"]:
            authorized_views[v["id"]] = v
            if v.get("redacted"):
                redacted_ids.add(v["id"])
        result.hits = [h for h in result.hits if h.claim.id in authorized_views]

    _check_pack_deadline(deadline_monotonic, stage="after_privacy")

    # Pack-time injection screen (stored memories are data, never instructions).
    result.hits, injection_blocked = screen_injection(result.hits)
    privacy_blocked.extend(injection_blocked)
    result.hits, drop_counts = dedupe_and_diversify(prefer_current(result.hits))
    _check_pack_deadline(deadline_monotonic, stage="after_dedupe")

    budget = max_tokens * CHARS_PER_TOKEN
    sections: list[str] = []
    sources: list[dict] = []
    confidences: list[float] = []
    used = 0

    def push(text: str, ceiling: Optional[int] = None) -> bool:
        nonlocal used
        cap = min(budget, ceiling) if ceiling is not None else budget
        if used + len(text) + 1 > cap:
            return False
        sections.append(text)
        used += len(text) + 1
        return True

    judgment_snapshot_id: Optional[str] = None
    applicable_stance_out: list = []
    applicable_judgment_out: list = []
    if include_judgment:
        _check_pack_deadline(deadline_monotonic, stage="before_judgment")
        judgment_text = ""
        pack_j: dict = {}
        if hasattr(store, "list_judgment_items"):
            from twin.cognize.stance_engine.application import applicable_pack, render_applicable
            from twin.cognize.stance_engine.models import AppliedRevisionRef, JudgmentItem
            from twin.cognize.stance_engine.versions import make_snapshot
            from ..privacy.engine import evaluate_judgment_items
            active = store.list_judgment_items(status="active", limit=1)
            if active:
                pack_j = applicable_pack(
                    store,
                    domain=target_domain or "technical",
                    task_profile=task_profile or "general",
                    project_id=project_id,
                    query=query,
                    persona=access.persona,
                    audience=access.audience,
                    client=access.tool_id,
                    persist_snapshot=False,
                )
                raw_items = []
                for key in ("hard_constraints", "principles", "heuristics",
                            "preferences", "beliefs", "values"):
                    for raw in pack_j.get(key) or []:
                        try:
                            raw_items.append(JudgmentItem.model_validate(raw))
                        except Exception:
                            continue
                gov = evaluate_judgment_items(
                    store, access, raw_items,
                    policies_path=cfg.policies_path, persist=True,
                )
                views_by_id = {v["id"]: v for v in gov["allowed"]}
                allowed_j = set(views_by_id)
                for key in ("hard_constraints", "principles", "heuristics",
                            "preferences", "beliefs", "values", "applicable_judgments"):
                    filtered = []
                    for it in pack_j.get(key) or []:
                        if it.get("id") not in allowed_j:
                            continue
                        view = views_by_id.get(it["id"]) or {}
                        # Full authorized judgment view — never mix canonical fields
                        authorized = {
                            "id": it["id"],
                            "kind": it.get("kind"),
                            "statement": view.get("summary") or it.get("statement") or "",
                            "domain": it.get("domain"),
                            "persona": it.get("persona"),
                            "strength": it.get("strength"),
                            "redacted": bool(view.get("redacted")),
                        }
                        if view.get("redacted"):
                            authorized["statement"] = view.get("summary") or "[redacted]"
                            authorized["description"] = None
                            authorized["provenance"] = None
                            authorized["exceptions"] = []
                            authorized["metadata"] = {"redacted": True}
                        else:
                            for field in ("description", "scope", "exceptions", "metadata"):
                                if field in it:
                                    authorized[field] = it[field]
                        filtered.append(authorized)
                    pack_j[key] = filtered
                for d in gov["denied"]:
                    privacy_blocked.append({
                        "claim_id": d.get("claim_id", ""),
                        "reason": f"judgment:{d.get('reason', '')}",
                        "rule": d.get("rule", "judgment_denied"),
                    })
                privacy_meta["judgment_privacy_decision_id"] = gov.get("decision_id")
                # Persist snapshot AFTER governance with authorized payloads only
                authorized_refs: list[AppliedRevisionRef] = []
                for ref in pack_j.get("applied_revisions") or []:
                    jid = ref.get("judgment_id")
                    if jid not in allowed_j:
                        continue
                    view = views_by_id.get(jid) or {}
                    payload = dict(ref.get("payload") or {})
                    if view.get("redacted"):
                        payload = {
                            "id": jid,
                            "statement": view.get("summary") or "[redacted]",
                            "redacted": True,
                        }
                    authorized_refs.append(AppliedRevisionRef(
                        judgment_id=jid,
                        revision_id=ref.get("revision_id") or "",
                        effective_strength=float(ref.get("effective_strength") or 0),
                        disabled=False,
                        payload=payload,
                    ))
                snap = make_snapshot(
                    store, authorized_refs,
                    context={
                        **(pack_j.get("context") or {}),
                        "privacy_decision_id": gov.get("decision_id"),
                        "policy_set_version": privacy_meta.get("policy_set_version"),
                    },
                    persist=True,
                )
                judgment_snapshot_id = snap.id
                pack_j["snapshot_id"] = snap.id
                judgment_text = render_applicable(pack_j)
                flat: list = []
                for key in (
                    "hard_constraints",
                    "principles",
                    "heuristics",
                    "preferences",
                    "beliefs",
                    "values",
                    "applicable_judgments",
                ):
                    for it in pack_j.get(key) or []:
                        if it.get("id") and it not in flat:
                            flat.append(it)
                pack_j["applicable_stance"] = list(flat)
                applicable_stance_out = list(flat)
                applicable_judgment_out = list(flat)
        if judgment_text:
            push(judgment_text[: int(budget * profile.judgment_share)])

    evidence_wanted = bool(
        profile.evidence_hits and _evidence_lines(
            store, result.hits, profile.evidence_hits, skip_ids=redacted_ids,
        )
    )
    evidence_reserve = 0
    if evidence_wanted:
        evidence_reserve = min(
            len("## Evidence") + 1 + profile.evidence_hits * EVIDENCE_LINE_CHARS,
            max(int(budget * 0.25), EVIDENCE_LINE_CHARS + 12),
            max(budget - used, 0),
        )

    memory_cap = budget - evidence_reserve
    memory_budget = memory_cap - used
    packed_hits: list[SearchHit] = []
    remaining = list(result.hits)
    for header, types, share in profile.sections:
        section_hits = [h for h in remaining if h.claim.type.value in types]
        if not section_hits:
            continue
        section_ceiling = min(used + max(int(memory_budget * share), 200), memory_cap)
        if not push(f"## {header}", ceiling=section_ceiling):
            continue
        for hit in section_hits:
            view = authorized_views.get(hit.claim.id) or {
                "id": hit.claim.id, "title": hit.claim.title,
                "summary": hit.claim.summary, "redacted": False,
            }
            status = hit.claim.status.value if hasattr(hit.claim.status, "value") else str(hit.claim.status)
            label = cognitive_label(hit.claim)
            if not push(
                _entry_from_view(view, status=status, label=label),
                ceiling=section_ceiling,
            ):
                break
            remaining.remove(hit)
            packed_hits.append(hit)
            confidences.append(hit.claim.confidence)
            sources.append(_source_meta(hit, view, label=label))
    leftover = [h for h in sorted(remaining, key=lambda h: h.score, reverse=True)]
    if leftover and used + 100 < memory_cap:
        pushed_header = False
        for hit in leftover:
            if not pushed_header:
                if not push("## Additional context", ceiling=memory_cap):
                    break
                pushed_header = True
            view = authorized_views.get(hit.claim.id) or {
                "id": hit.claim.id, "title": hit.claim.title,
                "summary": hit.claim.summary, "redacted": False,
            }
            status = hit.claim.status.value if hasattr(hit.claim.status, "value") else str(hit.claim.status)
            label = cognitive_label(hit.claim)
            if not push(
                _entry_from_view(view, status=status, label=label),
                ceiling=memory_cap,
            ):
                break
            packed_hits.append(hit)
            confidences.append(hit.claim.confidence)
            sources.append(_source_meta(hit, view, label=label))

    evidence_included = False
    evidence_omitted = False
    lines = _evidence_lines(
        store, packed_hits, profile.evidence_hits, skip_ids=redacted_ids,
    )
    if lines:
        if push("## Evidence"):
            for line in lines:
                if push(line):
                    evidence_included = True
                else:
                    evidence_omitted = True
        else:
            evidence_omitted = True
    elif evidence_wanted:
        evidence_omitted = True

    sections_text = "\n".join(sections) if sections else ""

    # Leakage + canary scans on the assembled pack
    if hasattr(store, "insert_privacy_decision"):
        from ..privacy.canaries import scan_for_canaries
        from ..privacy.redact import leakage_scan
        findings = leakage_scan(sections_text)
        leaked = scan_for_canaries(store, sections_text) if hasattr(store, "list_leakage_canaries") else []
        if findings or leaked:
            privacy_meta["leakage_findings"] = findings
            privacy_meta["canary_leak_blocked"] = bool(leaked)
            # Drop pack rather than ship leakage; do not silently pretend success
            sections_text = ""
            sources = []
            packed_hits = []
            privacy_blocked.append({
                "claim_id": "",
                "reason": "output_leakage_blocked",
                "rule": "leakage_scan" if findings else "canary",
            })

    if "do_not_cache" in (privacy_meta.get("obligations") or []):
        privacy_meta["cacheable"] = False

    blocked = [{"claim_id": b.claim_id, "reason": b.rule} for b in result.blocked]
    for b in privacy_blocked:
        blocked.append({
            "claim_id": b.get("claim_id", ""),
            "reason": b.get("reason", b.get("rule", "privacy")),
        })

    goals = project_goals(store, project_id)
    active = {
        "project": project_id,
        "domain": target_domain,
        "persona": access.persona,
        "session_id": session_id or access.session_id,
        "goals": goals,
    }
    provenance = build_provenance_summary(store, packed_hits)
    low_conf = [h.claim.id for h in packed_hits if h.claim.confidence < 0.55]
    uncertainty = {
        "low_confidence_ids": low_conf,
        "open_conflicts": [
            h.claim.id for h in packed_hits
            if "conflict" in (h.claim.quality_flags or [])
            or "possible_conflict" in (h.claim.quality_flags or [])
        ],
    }
    explanation = {
        "profile": profile.name,
        "dropped": drop_counts,
        "injection_blocked": [
            b.get("claim_id") for b in injection_blocked if b.get("claim_id")
        ],
        "blocked_count": len(blocked),
        "mode": mode,
    }
    token_budget = {
        "max": max_tokens,
        "used_chars": used,
        "max_chars": budget,
        "evidence_reserved_chars": evidence_reserve,
    }
    _check_pack_deadline(deadline_monotonic, stage="before_format")
    pack_text = render_pack(
        mode=mode,
        sections_text=sections_text,
        provenance=provenance,
        active=active,
        explanation=explanation,
        uncertainty=uncertainty,
    )

    narratives_out: list = []
    reflections_out: list = []
    epistemic_out: list = []
    derived_conf: dict = {}
    if hasattr(store, "list_narratives"):
        from twin.cognize.models import EpistemicStatus, derive_confidence
        from twin.cognize.models import RelationType

        vault = "default"
        if access and isinstance(getattr(access, "metadata", None), dict):
            vault = str(access.metadata.get("vault_id") or vault)
        for nar in store.list_narratives(vault):
            if nar.domain and nar.domain != target_domain and target_domain not in ("general", "*"):
                continue
            if access is not None:
                from twin.cognize.acl import narrative_visible_to_access

                if not narrative_visible_to_access(nar, access):
                    privacy_blocked.append({
                        "claim_id": nar.id,
                        "reason": "narrative_acl",
                        "rule": "sensitivity_audience",
                    })
                    blocked.append({
                        "claim_id": nar.id,
                        "reason": "narrative_acl",
                    })
                    continue
            eps = (
                store.get_epistemic_state(nar.epistemic_state_id)
                if nar.epistemic_state_id
                else None
            )
            if eps and eps.status is EpistemicStatus.tombstoned:
                continue
            entry = {
                "narrative_id": nar.id,
                "account": nar.account if not (eps and eps.status is EpistemicStatus.stale) else None,
                "grain": nar.grain.value if nar.grain else None,
                "domain": nar.domain,
                "epistemic_status": eps.status.value if eps else "unknown",
                "stale_reason": eps.stale_reason if eps else "",
                "synthesized_at": eps.synthesized_at if eps else "",
                "evidence_ids": list(nar.evidence_ids),
                "derived": True,
            }
            if eps and eps.status is EpistemicStatus.stale:
                entry["account_omitted"] = True
                entry["note"] = "stale — withheld as fresh; re-synthesize or proceed knowingly"
            else:
                entry["account_omitted"] = False
            narratives_out.append(entry)
            if eps:
                epistemic_out.append(eps.model_dump(mode="json"))
                evid = list(eps.evidence_ids or nar.evidence_ids)
                evid_set = set(evid)
                groups = []
                support_count = 0
                contradict_count = 0
                dissent_ids: list[str] = []
                if hasattr(store, "list_relations"):
                    sod = store.list_relations(
                        vault,
                        rel_type=RelationType.same_originating_decision.value,
                    )
                    for rel in sod:
                        pair = [rel.from_id, rel.to_id]
                        if evid_set.intersection(pair):
                            groups.append(pair)
                    for rel in store.list_relations(
                        vault, rel_type=RelationType.supports.value
                    ):
                        if rel.to_id in evid_set or rel.from_id in evid_set:
                            support_count += 1
                    for rel in store.list_relations(
                        vault, rel_type=RelationType.contradicts.value
                    ):
                        if rel.to_id in evid_set or rel.from_id in evid_set:
                            contradict_count += 1
                            dissent_ids.append(rel.id)
                derived = derive_confidence(
                    evidence_ids=evid,
                    same_originating_decision_groups=groups,
                    support_count=support_count,
                    contradict_count=contradict_count,
                    epistemic_status=eps.status,
                )
                derived_conf[nar.id] = {
                    **derived.model_dump(mode="json"),
                    "derived": True,
                    "supports": support_count,
                    "contradicts": contradict_count,
                    "retained_dissent": dissent_ids[:8],
                }
                entry["retained_dissent"] = dissent_ids[:8]
        if hasattr(store, "list_open_reflections"):
            for ref in store.list_open_reflections(vault):
                ref_domain = (ref.metadata or {}).get("domain") or ""
                ref_sens = (ref.metadata or {}).get("sensitivity") or "internal"
                if ref_domain and ref_domain != target_domain and target_domain not in (
                    "general", "*",
                ):
                    privacy_blocked.append({
                        "claim_id": ref.id,
                        "reason": "reflection_domain",
                        "rule": "open_reflection_firewall",
                    })
                    blocked.append({
                        "claim_id": ref.id,
                        "reason": "reflection_domain",
                    })
                    continue
                if access is not None:
                    audience = getattr(access, "audience", None) or "self"
                    if ref_sens in ("private", "restricted") and audience not in (
                        "self", "owner",
                    ):
                        privacy_blocked.append({
                            "claim_id": ref.id,
                            "reason": "reflection_acl",
                            "rule": "sensitivity_audience",
                        })
                        blocked.append({
                            "claim_id": ref.id,
                            "reason": "reflection_acl",
                        })
                        continue
                reflections_out.append(
                    {
                        "reflection_id": ref.id,
                        "text": ref.text,
                        "status": ref.status.value,
                        "derived": True,
                    }
                )
        uncertainty = dict(uncertainty)
        uncertainty["open_reflections"] = [r["reflection_id"] for r in reflections_out]
        if reflections_out:
            # Respect remaining pack budget (~4 chars/token heuristic).
            budget_chars = max(0, int(max_tokens or 1200) * 4 - len(pack_text or ""))
            lines: list[str] = []
            used = 0
            for r in reflections_out[:8]:
                line = f"- {r['text']}"
                if used + len(line) + 1 > budget_chars and lines:
                    break
                lines.append(line)
                used += len(line) + 1
            if lines:
                extra = "\n## Open Reflections\n" + "\n".join(lines)
                pack_text = pack_text + "\n" + extra
        stale_nars = [n for n in narratives_out if n.get("epistemic_status") == "stale"]
        fresh_nars = [n for n in narratives_out if n.get("epistemic_status") == "fresh" and n.get("account")]
        if fresh_nars:
            pack_text += "\n## Narratives\n" + "\n".join(
                f"- [{n['narrative_id']}] {n['account']}" for n in fresh_nars[:5]
            )
        if stale_nars:
            pack_text += "\n## Stale Narratives (not current)\n" + "\n".join(
                f"- [{n['narrative_id']}] stale: {n.get('stale_reason') or 'new evidence'}"
                for n in stale_nars[:5]
            )
        if hasattr(store, "append_trace"):
            from twin.cognize.models import Trace as CogTrace

            for n in narratives_out[:20]:
                store.append_trace(
                    CogTrace(
                        vault_id=vault,
                        event_kind="pack_serve",
                        resource_kind="narrative",
                        resource_id=n["narrative_id"],
                        session_id=session_id,
                        metadata={"epistemic_status": n.get("epistemic_status")},
                    )
                )

    return ContextPack(
        context_pack=pack_text,
        sources=sources,
        confidence=round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
        blocked=blocked,
        task_profile=profile.name,
        project_id=project_id,
        judgment_snapshot_id=judgment_snapshot_id,
        privacy_decision_id=privacy_decision_id,
        privacy_meta=privacy_meta,
        evidence_included=evidence_included,
        evidence_omitted_due_to_budget=evidence_omitted,
        mode=mode,
        request_scope=request_scope or query,
        active=active,
        uncertainty=uncertainty,
        provenance_summary=provenance,
        token_budget=token_budget,
        blocked_count=len(blocked),
        explanation=explanation,
        narratives=narratives_out,
        open_reflections=reflections_out,
        epistemic=epistemic_out,
        derived_confidence=derived_conf,
        applicable_stance=applicable_stance_out,
        applicable_judgment=applicable_judgment_out,
    )


def _source_meta(hit: SearchHit, view: dict, *, label: str = "ok") -> dict:
    if view.get("redacted"):
        return {
            "claim_id": f"opaque_{hit.claim.id[-8:]}",
            "redacted": True,
            "why_relevant": "authorized contextual match",
            "percept_ids": [],
            "status": "redacted",
            "label": "redacted",
        }
    return {
        "claim_id": hit.claim.id,
        "title": view.get("title", hit.claim.title),
        "confidence": hit.claim.confidence,
        "status": hit.claim.status.value,
        "percept_ids": hit.claim.percept_ids,
        "why_relevant": hit.why,
        "redacted": False,
        "label": label,
    }
