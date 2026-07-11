"""README §27 improvements — one test block per item."""

from pathlib import Path

import pytest

from twin import ids
from twin.cognition import extract_percept
from twin.cognition.context_pack import build_context_pack
from twin.cognition.observer import infer_domain
from twin.judgment.profile import load_profile, promote_memory
from twin.memory.lifecycle import contradict, supersede
from twin.memory.metrics import compute_metrics
from twin.memory.models import MemoryItem, MemoryStatus
from twin.sensory import sense_paths
from twin.sensory.percept import Percept

EXAMPLES = Path(__file__).parent.parent / "examples"


def _mem(store, embedder, confirmed=True, **kw):
    base = dict(id=ids.memory_id(), type="fact", title="t", summary="s",
                domain="technical", confidence=0.9,
                status="confirmed" if confirmed else "candidate")
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(mem.id, "memory", embedder.name,
                          embedder.embed(f"{mem.title}\n{mem.summary}"))
    return mem


def _populate(store, cfg, embedder):
    percepts, _ = sense_paths([EXAMPLES])
    for p in percepts:
        store.insert_percept(p)
        extract_percept(store, cfg, embedder, p)


# -- 27.1: candidates blocked by default in packs ---------------------------

def test_pack_excludes_candidates_by_default(store, cfg, embedder):
    _populate(store, cfg, embedder)  # heuristic output → all candidates
    pack = build_context_pack(store, cfg, embedder, "FastAPI webhooks Atlas")
    assert pack.sources == []  # nothing confirmed yet

    pack_loose = build_context_pack(store, cfg, embedder, "FastAPI webhooks Atlas",
                                    include_candidates=True)
    assert pack_loose.sources
    assert "[candidate]" in pack_loose.context_pack


def test_pack_includes_confirmed(store, cfg, embedder):
    _mem(store, embedder, type="decision",
         title="Usar FastAPI nos webhooks", summary="Decisão: FastAPI no backend de webhooks.")
    pack = build_context_pack(store, cfg, embedder, "FastAPI webhooks")
    assert len(pack.sources) == 1
    assert pack.sources[0]["status"] == "confirmed"


# -- 27.2: sectioned packs ---------------------------------------------------

def test_pack_is_sectioned_with_evidence(store, cfg, embedder):
    percepts, _ = sense_paths([EXAMPLES / "transcripts"])
    percept = percepts[0]
    store.insert_percept(percept)
    report = extract_percept(store, cfg, embedder, percept)
    for mid in report.inserted:
        store.set_status(mid, MemoryStatus.confirmed)
    pack = build_context_pack(store, cfg, embedder,
                              "FastAPI webhooks Atlas decisões tarefas", max_tokens=2000)
    assert "## Judgment profile" in pack.context_pack
    assert "## Decisions" in pack.context_pack
    assert "## Open tasks" in pack.context_pack
    assert "## Evidence" in pack.context_pack
    # evidence quotes reference memory ids
    assert '[mem_' in pack.context_pack


# -- 27.3: source_trust / source_scope / source_confidentiality ---------------

def test_source_fields_roundtrip(store):
    percepts, _ = sense_paths([EXAMPLES / "transcripts"])
    percept = percepts[0]
    assert percept.source_trust == 0.7  # meeting transcript sensor default
    store.insert_percept(percept)
    loaded = store.get_percept(percept.id)
    assert loaded.source_trust == pytest.approx(0.7)
    assert loaded.source_scope == "work"
    assert loaded.source_confidentiality == "internal"


def test_source_trust_scales_confidence_and_floors_sensitivity(store, cfg, embedder):
    percept = Percept(percept_type="slack_thread", source_sensor="slack",
                      content="Marina: decidimos usar FastAPI no backend.",
                      source_trust=0.5, source_scope="work",
                      source_confidentiality="private").seal()
    store.insert_percept(percept)
    report = extract_percept(store, cfg, embedder, percept)
    mem = store.get_memory(report.inserted[0])
    assert mem.confidence == pytest.approx(0.5 * 0.5)  # heuristic 0.5 × trust 0.5
    assert mem.sensitivity.value == "private"           # floor from source
    assert mem.needs_review


# -- 27.4: promote memory to judgment ------------------------------------------

def test_promote_preference_to_judgment(store, cfg, embedder):
    mem = _mem(store, embedder, type="preference",
               title="ADRs no repo", summary="Prefere ADRs no próprio repositório.")
    section = promote_memory(cfg.judgment_path, mem)
    assert section == "promoted_preferences"
    profile = load_profile(cfg.judgment_path)
    entries = profile["promoted_preferences"]
    assert entries[0]["memory_id"] == mem.id
    # idempotent
    promote_memory(cfg.judgment_path, mem)
    assert len(load_profile(cfg.judgment_path)["promoted_preferences"]) == 1
    # promoted content rides along in packs via the judgment section
    pack = build_context_pack(store, cfg, embedder, "qualquer tarefa")
    assert "ADRs no próprio repositório" in pack.context_pack


def test_promote_rejects_non_judgment_types(store, cfg, embedder):
    mem = _mem(store, embedder, type="event", title="reunião", summary="houve reunião")
    with pytest.raises(ValueError):
        promote_memory(cfg.judgment_path, mem)


# -- 27.5: observer domain inference uses the graph ------------------------------

def test_infer_domain_uses_graph_entities(store, embedder):
    _mem(store, embedder, type="preference", domain="assistant_preferences",
         title="Respostas diretas", summary="Prefere respostas diretas.",
         entities=["Falstaff"])
    # no keywords at all — only the entity connects to a domain
    assert infer_domain("o que você sabe sobre Falstaff?", store) == "assistant_preferences"
    # keywords still win without a store
    assert infer_domain("o que você sabe sobre Falstaff?") == "technical"


# -- 27.7: optional local encryption -----------------------------------------------

def test_encryption_at_rest_roundtrip(tmp_path):
    from twin.memory.crypto import build_codec
    from twin.memory.models import Evidence
    from twin.memory.store.sqlite import SqliteStore

    codec = build_codec("senha-super-secreta", tmp_path)
    store = SqliteStore(tmp_path / "enc.db", codec=codec)
    percept = Percept(percept_type="document", source_sensor="document",
                      content="conteúdo sigiloso do documento").seal()
    store.insert_percept(percept)

    # plaintext never touches disk
    raw = store.conn.execute("SELECT content FROM percepts").fetchone()[0]
    assert raw.startswith("enc1:")
    assert "sigiloso" not in raw
    # transparent decryption on read
    assert store.get_percept(percept.id).content == "conteúdo sigiloso do documento"

    mem = MemoryItem(id=ids.memory_id(), type="fact", title="t", summary="s")
    store.insert_memory(mem)
    store.insert_evidence(Evidence(id=ids.evidence_id(), memory_id=mem.id,
                                   percept_id=percept.id, quote="trecho sigiloso"))
    raw_quote = store.conn.execute("SELECT quote FROM evidence").fetchone()[0]
    assert raw_quote.startswith("enc1:")
    assert store.get_evidence(mem.id)[0].quote == "trecho sigiloso"
    store.close()


def test_plaintext_readthrough_after_enabling_encryption(tmp_path):
    from twin.memory.crypto import build_codec
    from twin.memory.store.sqlite import SqliteStore

    plain = SqliteStore(tmp_path / "mix.db")
    percept = Percept(percept_type="document", source_sensor="document",
                      content="escrito antes da criptografia").seal()
    plain.insert_percept(percept)
    plain.close()

    codec = build_codec("senha", tmp_path)
    enc = SqliteStore(tmp_path / "mix.db", codec=codec)
    assert enc.get_percept(percept.id).content == "escrito antes da criptografia"
    enc.close()


# -- 27.8: quality metrics -----------------------------------------------------------

def test_metrics(store, cfg, embedder):
    _populate(store, cfg, embedder)
    memories = store.list_memories()
    store.set_status(memories[0].id, MemoryStatus.confirmed)
    store.set_status(memories[1].id, MemoryStatus.rejected)
    metrics = compute_metrics(store)
    assert metrics["percepts"]["total"] == 3
    assert metrics["memories"]["total"] == len(memories)
    assert metrics["memories"]["by_status"]["confirmed"] == 1
    assert metrics["quality"]["approval_rate"] == 0.5
    assert 0 <= metrics["memories"]["avg_confidence"] <= 1


# -- 27.9: explicit supersedence / contradiction ---------------------------------------

def test_supersede_closes_old_memory(store, embedder):
    old = _mem(store, embedder, type="belief", title="microservices",
               summary="Prefere microservices.", valid_from="2023-01-01")
    new = _mem(store, embedder, type="belief", title="modular monolith",
               summary="Prefere modular monolith.", valid_from="2026-07-01")
    result = supersede(store, new.id, old.id)
    reloaded = store.get_memory(old.id)
    assert reloaded.status.value == "deprecated"
    assert reloaded.valid_until == "2026-07-01"
    rels = store.relations_for(new.id)
    assert any(r.predicate == "supersedes" and r.object_id == old.id for r in rels)
    assert result.action == "supersede"


def test_contradict_flags_both_for_review(store, embedder):
    a = _mem(store, embedder, title="usa tabs", summary="Prefere tabs.")
    b = _mem(store, embedder, title="usa espaços", summary="Prefere espaços.")
    contradict(store, a.id, b.id)
    assert store.get_memory(b.id).status.value == "contradicted"
    assert store.get_memory(a.id).needs_review
    assert store.get_memory(b.id).needs_review
    rels = store.relations_for(a.id)
    assert any(r.predicate == "contradicts" for r in rels)


def test_lifecycle_rejects_self_reference(store, embedder):
    mem = _mem(store, embedder)
    with pytest.raises(ValueError):
        supersede(store, mem.id, mem.id)
    with pytest.raises(ValueError):
        contradict(store, mem.id, mem.id)
