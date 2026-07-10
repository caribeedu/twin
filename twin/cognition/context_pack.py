"""safe_context_pack — recall, packaged for external LLMs.

Given a task description and a target domain, returns a compact, firewall-
filtered context pack ready to prepend to an external LLM's prompt, with
sources and the list of blocked memories (ids + rule only, never content).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from ..config import Config
from ..judgment.firewall import Firewall
from ..judgment.profile import load_profile, render_profile
from ..memory.embeddings import Embedder
from ..memory.search import search
from ..memory.store.base import MemoryStore

CHARS_PER_TOKEN = 4  # rough heuristic; packs are small so precision is not critical


@dataclass
class ContextPack:
    context_pack: str
    sources: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    blocked: list[dict] = field(default_factory=list)


def build_context_pack(
    store: MemoryStore,
    cfg: Config,
    embedder: Embedder,
    query: str,
    target_domain: str = "technical",
    max_tokens: int = 1200,
    include_judgment: bool = True,
    firewall: Optional[Firewall] = None,
) -> ContextPack:
    firewall = firewall or Firewall(cfg.policies_path, store)
    result = search(
        store, embedder, query,
        target_domain=target_domain, firewall=firewall, limit=20,
    )

    budget = max_tokens * CHARS_PER_TOKEN
    sections: list[str] = []
    sources: list[dict] = []
    confidences: list[float] = []

    if include_judgment:
        judgment_text = render_profile(load_profile(cfg.judgment_path))
        if judgment_text:
            # judgment gets at most a third of the budget
            sections.append(judgment_text[: budget // 3])

    used = sum(len(s) for s in sections)
    if result.hits:
        sections.append("## Relevant memories")
    for hit in result.hits:
        mem = hit.memory
        status_tag = "" if mem.status.value == "confirmed" else f" [{mem.status.value}]"
        entry = (
            f"- ({mem.type.value}{status_tag}, {mem.valid_from or mem.created_at[:10]}) "
            f"{mem.title}: {mem.summary}"
        )
        if used + len(entry) > budget:
            break
        sections.append(entry)
        used += len(entry)
        confidences.append(mem.confidence)
        sources.append({
            "memory_id": mem.id,
            "title": mem.title,
            "confidence": mem.confidence,
            "status": mem.status.value,
            "percept_ids": mem.percept_ids,
            "why_relevant": hit.why,
        })

    pack_text = "\n".join(sections) if sources else ""
    return ContextPack(
        context_pack=pack_text,
        sources=sources,
        confidence=round(sum(confidences) / len(confidences), 3) if confidences else 0.0,
        blocked=[{"memory_id": b.memory_id, "reason": b.rule} for b in result.blocked],
    )
