from pathlib import Path

from twin.cognition import extract_pending
from twin.cognition.context_pack import build_context_pack
from twin.cognition.observer import infer_domain, observe
from twin.judgment.firewall import Firewall
from twin.memory.search import search
from twin.sensory import sense_paths
from twin.privacy.identity import ensure_local_identity, resolve_access
from twin.privacy.yaml_io import bootstrap_policy_set


def _cli_access(store):
    bootstrap_policy_set(store)
    ensure_local_identity(store)
    return resolve_access(store, surface="cli", persona="individual",
                          purpose="memory_retrieval", audience="self")


EXAMPLES = Path(__file__).parent.parent / "examples"


def _populate(store, cfg, embedder):
    percepts, _ = sense_paths([EXAMPLES])
    for p in percepts:
        store.insert_percept(p)
    extract_pending(store, cfg, embedder)


def test_search_finds_fastapi_decision(store, cfg, embedder):
    _populate(store, cfg, embedder)
    fw = Firewall(cfg.policies_path, store)
    result = search(store, embedder, "qual framework usamos no backend de webhooks FastAPI",
                    target_domain="technical", firewall=fw)
    assert result.hits
    top_texts = " ".join(h.memory.summary for h in result.hits[:3])
    assert "FastAPI" in top_texts


def test_search_blocks_cross_domain(store, cfg, embedder):
    _populate(store, cfg, embedder)
    # plant a relationship-domain memory that matches the query text
    from twin import ids
    from twin.memory.models import MemoryItem

    mem = MemoryItem(id=ids.memory_id(), type="fact", title="jantar de aniversário FastAPI piada",
                     summary="conversa pessoal mencionando FastAPI", domain="relationship",
                     sensitivity="private", confidence=0.9, status="confirmed")
    store.insert_memory(mem)
    store.store_embedding(mem.id, "memory", embedder.name,
                          embedder.embed(mem.title + " " + mem.summary))

    fw = Firewall(cfg.policies_path, store)
    result = search(store, embedder, "FastAPI backend webhooks",
                    target_domain="work", firewall=fw)
    assert any(b.memory_id == mem.id for b in result.blocked)
    assert all(h.memory.id != mem.id for h in result.hits)


def test_context_pack_respects_budget_and_includes_judgment(store, cfg, embedder):
    _populate(store, cfg, embedder)
    # heuristic extraction yields candidates only → opt in explicitly
    pack = build_context_pack(store, cfg, embedder, "escrever RFC sobre webhooks do Atlas",
                              target_domain="technical", max_tokens=400,
                              include_candidates=True, access=_cli_access(store))
    assert pack.context_pack
    assert len(pack.context_pack) <= 400 * 4 + 200  # small tolerance
    assert "Judgment" in pack.context_pack or pack.sources
    assert pack.sources
    assert all("percept_ids" in s for s in pack.sources)


def test_observer_suggests_and_infers_domain(store, cfg, embedder):
    _populate(store, cfg, embedder)
    assert infer_domain("preciso revisar a arquitetura do deploy") == "technical"
    suggestion = observe(store, cfg, embedder,
                         "vou escrever a RFC de arquitetura dos webhooks do Atlas")
    assert suggestion.inferred_domain == "technical"
    assert suggestion.suggested_context
    for item in suggestion.suggested_context:
        assert item["allowed"] is True
        assert item["memory_id"].startswith("mem_")


def _confirmed_mem(store, embedder, **kw):
    from twin import ids
    from twin.memory.models import MemoryItem

    base = dict(id=ids.memory_id(), type="fact", title="t", summary="s",
                domain="technical", confidence=0.9, status="confirmed")
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(mem.id, "memory", embedder.name,
                          embedder.embed(f"{mem.title}\n{mem.summary}"))
    return mem


def test_pack_excludes_candidates_by_default(store, cfg, embedder):
    _populate(store, cfg, embedder)  # heuristic output → all candidates
    pack = build_context_pack(store, cfg, embedder, "FastAPI webhooks Atlas", access=_cli_access(store))
    assert pack.sources == []  # nothing confirmed yet

    pack_loose = build_context_pack(store, cfg, embedder, "FastAPI webhooks Atlas",
                                    include_candidates=True, access=_cli_access(store))
    assert pack_loose.sources
    assert "[candidate]" in pack_loose.context_pack


def test_pack_includes_confirmed(store, cfg, embedder):
    _confirmed_mem(store, embedder, type="decision",
                   title="Usar FastAPI nos webhooks",
                   summary="Decisão: FastAPI no backend de webhooks.")
    pack = build_context_pack(store, cfg, embedder, "FastAPI webhooks", access=_cli_access(store))
    assert len(pack.sources) == 1
    assert pack.sources[0]["status"] == "confirmed"


def test_pack_is_sectioned_with_evidence(store, cfg, embedder):
    from twin.cognition import extract_percept
    from twin.memory.models import MemoryStatus

    percepts, _ = sense_paths([EXAMPLES / "transcripts"])
    percept = percepts[0]
    store.insert_percept(percept)
    report = extract_percept(store, cfg, embedder, percept)
    for mid in report.inserted:
        store.set_status(mid, MemoryStatus.confirmed)
    pack = build_context_pack(store, cfg, embedder,
                              "FastAPI webhooks Atlas decisões tarefas", max_tokens=2000, access=_cli_access(store))
    assert "## Decisions" in pack.context_pack
    assert "## Open tasks" in pack.context_pack
    assert "## Evidence" in pack.context_pack
    # evidence quotes reference memory ids
    assert "[mem_" in pack.context_pack


def test_pack_evidence_survives_tight_budgets(store, cfg, embedder):
    """Evidence space is reserved before memory sections are packed, so a
    full pack can never silently squeeze the quotes out — and the flags say
    exactly what happened."""
    from twin.cognition import extract_percept
    from twin.memory.models import MemoryStatus

    percepts, _ = sense_paths([EXAMPLES / "transcripts"])
    store.insert_percept(percepts[0])
    report = extract_percept(store, cfg, embedder, percepts[0])
    for mid in report.inserted:
        store.set_status(mid, MemoryStatus.confirmed)

    tight = build_context_pack(store, cfg, embedder,
                               "FastAPI webhooks Atlas decisões tarefas",
                               max_tokens=400, access=_cli_access(store))
    assert tight.sources  # memories still fit
    assert tight.evidence_included  # at least one quote made it in
    assert "## Evidence" in tight.context_pack

    roomy = build_context_pack(store, cfg, embedder,
                               "FastAPI webhooks Atlas decisões tarefas",
                               max_tokens=4000, access=_cli_access(store))
    assert roomy.evidence_included
    assert not roomy.evidence_omitted_due_to_budget


def test_pack_unused_section_budget_is_redistributed(store, cfg, embedder):
    """Space reserved for absent section types flows to the best remaining
    hits instead of shipping a half-empty pack."""
    for i in range(12):
        _confirmed_mem(store, embedder, type="fact",
                       title=f"Webhook fact {i}",
                       summary=f"Webhook delivery detail number {i}, "
                               "retries use exponential backoff.")
    # 500 tokens → the facts section alone caps at ~4 entries; the rest of
    # the budget would previously go unused
    pack = build_context_pack(store, cfg, embedder, "webhook delivery retries",
                              max_tokens=500, include_judgment=False, access=_cli_access(store))
    assert "## Additional context" in pack.context_pack
    in_section = pack.context_pack.split("## Additional context")[0].count("- (")
    assert len(pack.sources) > in_section  # carry-over actually added hits


def test_infer_domain_uses_graph_entities(store, embedder):
    _confirmed_mem(store, embedder, type="preference", domain="assistant_preferences",
                   title="Respostas diretas", summary="Prefere respostas diretas.",
                   entities=["Falstaff"])
    # no keywords at all — only the entity connects to a domain
    assert infer_domain("o que você sabe sobre Falstaff?", store) == "assistant_preferences"
    # without the graph there is no evidence — never assume a real domain
    assert infer_domain("o que você sabe sobre Falstaff?") == "unclassified"


def test_inactive_statuses_excluded_from_search(store, embedder):
    from twin import ids
    from twin.memory.lifecycle import archive_memory
    from twin.memory.models import MemoryItem

    live = MemoryItem(
        id=ids.memory_id(), type="fact", title="live fact",
        summary="Twin is local-first.", domain="technical",
        confidence=0.9, status="confirmed", entities=["Twin"],
    )
    dead = MemoryItem(
        id=ids.memory_id(), type="fact", title="dead fact",
        summary="Twin is local-first forever.", domain="technical",
        confidence=0.9, status="merged", entities=["Twin"],
    )
    store.insert_memory(live)
    store.insert_memory(dead)
    store.store_embedding(live.id, "memory", embedder.name,
                          embedder.embed(f"{live.title}\n{live.summary}"))
    store.store_embedding(dead.id, "memory", embedder.name,
                          embedder.embed(f"{dead.title}\n{dead.summary}"))
    archive_memory(store, dead.id)
    result = search(store, embedder, "local-first", include_candidates=False)
    ids_hit = {h.memory.id for h in result.hits}
    assert dead.id not in ids_hit
