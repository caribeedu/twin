"""Judgment profile: loading, rendering and promoting memories into it."""

import pytest

from twin import ids
from twin.cognition.context_pack import build_context_pack
from twin.judgment.profile import load_profile, promote_memory, render_profile
from twin.memory.models import MemoryItem


def _mem(store, embedder, **kw):
    base = dict(id=ids.memory_id(), type="fact", title="t", summary="s",
                domain="technical", confidence=0.9, status="confirmed")
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(mem.id, "memory", embedder.name,
                          embedder.embed(f"{mem.title}\n{mem.summary}"))
    return mem


def test_default_profile_loads_and_renders(cfg):
    profile = load_profile(cfg.judgment_path)
    assert profile["principles"]
    text = render_profile(profile)
    assert text.startswith("## Judgment profile")
    assert "privacidade" in text


def test_promote_preference_to_judgment(store, cfg, embedder):
    mem = _mem(store, embedder, type="preference",
               title="ADRs no repo", summary="Prefere ADRs no próprio repositório.")
    section = promote_memory(cfg.judgment_path, mem)
    assert section == "promoted_preferences"
    entries = load_profile(cfg.judgment_path)["promoted_preferences"]
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
