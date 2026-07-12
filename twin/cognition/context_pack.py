"""safe_context_pack — recall, packaged for external LLMs.

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
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..config import Config
from ..judgment.firewall import Firewall
from ..judgment.profile import load_profile, render_profile
from ..memory.embeddings import Embedder
from ..memory.search import SearchHit
from ..memory.store.base import MemoryStore
from .retrieval import Reranker, retrieve
from .task_profiles import get_profile

CHARS_PER_TOKEN = 4  # rough heuristic; packs are small so precision is not critical


@dataclass
class ContextPack:
    context_pack: str
    sources: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    blocked: list[dict] = field(default_factory=list)
    task_profile: str = "general"
    project_id: Optional[str] = None


def _entry(hit: SearchHit) -> str:
    mem = hit.memory
    status_tag = "" if mem.status.value == "confirmed" else f" [{mem.status.value}]"
    date = mem.valid_from or mem.created_at[:10]
    return f"- ({date}{status_tag}) {mem.title}: {mem.summary}"


def build_context_pack(
    store: MemoryStore,
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
) -> ContextPack:
    firewall = firewall or Firewall(cfg.policies_path, store)
    profile = get_profile(task_profile)
    result = retrieve(
        store, embedder, query,
        target_domain=target_domain, firewall=firewall, limit=25,
        include_candidates=include_candidates, project_id=project_id,
        reranker=reranker,
    )

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

    if include_judgment:
        judgment_text = render_profile(load_profile(cfg.judgment_path))
        if judgment_text:
            push(judgment_text[: int(budget * profile.judgment_share)])

    memory_budget = budget - used
    packed_hits: list[SearchHit] = []
    remaining = list(result.hits)
    for header, types, share in profile.sections:
        section_hits = [h for h in remaining if h.memory.type.value in types]
        if not section_hits:
            continue
        section_ceiling = used + max(int(memory_budget * share), 200)
        if not push(f"## {header}", ceiling=section_ceiling):
            continue
        for hit in section_hits:
            if not push(_entry(hit), ceiling=section_ceiling):
                break
            remaining.remove(hit)
            packed_hits.append(hit)
            confidences.append(hit.memory.confidence)
            sources.append({
                "memory_id": hit.memory.id,
                "title": hit.memory.title,
                "confidence": hit.memory.confidence,
                "status": hit.memory.status.value,
                "percept_ids": hit.memory.percept_ids,
                "why_relevant": hit.why,
            })

    # verbatim evidence for the strongest hits (traceability)
    top = sorted(packed_hits, key=lambda h: h.score, reverse=True)[:profile.evidence_hits]
    evidence_lines: list[str] = []
    for hit in top:
        for ev in store.get_evidence(hit.memory.id)[:1]:
            quote = ev.quote if len(ev.quote) <= 220 else ev.quote[:217] + "..."
            evidence_lines.append(f'- [{hit.memory.id}] "{quote}"')
    if evidence_lines and push("## Evidence"):
        for line in evidence_lines:
            if not push(line):
                break

    # judgment rides along even when no memory matches — how the user thinks
    # is useful context for any task
    pack_text = "\n".join(sections) if sections else ""
    return ContextPack(
        context_pack=pack_text,
        sources=sources,
        confidence=round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
        blocked=[{"memory_id": b.memory_id, "reason": b.rule} for b in result.blocked],
        task_profile=profile.name,
        project_id=project_id,
    )
