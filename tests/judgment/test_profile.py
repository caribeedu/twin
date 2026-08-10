"""Judgment profile: loading, rendering and promoting memories into it."""

import pytest

from twin import ids
from twin.inject.context_pack import build_context_pack
from twin.cognize.stance_engine.profile import load_profile, promote_memory, render_profile
from twin.store.models import MemoryItem
from twin.privacy.identity import ensure_local_identity, resolve_access
from twin.privacy.yaml_io import bootstrap_policy_set


def _cli_access(store):
    bootstrap_policy_set(store)
    ensure_local_identity(store)
    return resolve_access(store, surface="cli", persona="individual",
                          purpose="memory_retrieval", audience="self")



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
    # YAML promotion is bootstrap/export only — runtime packs do not load
    # judgment.yaml (would bypass governance). Preference remains in YAML profile.
    assert any(
        e["memory_id"] == mem.id
        for e in load_profile(cfg.judgment_path)["promoted_preferences"]
    )


def test_promote_rejects_non_judgment_types(store, cfg, embedder):
    mem = _mem(store, embedder, type="event", title="reunião", summary="houve reunião")
    with pytest.raises(ValueError):
        promote_memory(cfg.judgment_path, mem)
