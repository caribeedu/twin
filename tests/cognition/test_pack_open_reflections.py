"""Open reflections firewall + pack independence integration."""

from __future__ import annotations

from twin.cognize.models import Reflection, ReflectionStatus
from twin.inject.context_pack import build_context_pack
from twin.store.embeddings import HashEmbedder
from twin.privacy.models import AccessRequest


def test_open_reflections_acl_blocks_private_text(store, cfg):
    store.upsert_reflection(
        Reflection(
            vault_id="default",
            text="SECRET_REFLECTION_BODY",
            status=ReflectionStatus.open,
            metadata={"domain": "technical", "sensitivity": "private"},
        )
    )
    access = AccessRequest(
        audience="client",
        principal_id="ext",
        persona="individual",
        purpose="memory_retrieval",
        tool_id="test",
        requested_domains=["technical"],
        metadata={"vault_id": "default"},
    )
    pack = build_context_pack(
        store, cfg, HashEmbedder(),
        query="anything",
        target_domain="technical",
        access=access,
    )
    assert pack.open_reflections == []
    assert "SECRET_REFLECTION_BODY" not in (pack.context_pack or "")
    assert any(b.get("reason") == "reflection_acl" for b in (pack.blocked or []))


def test_open_reflections_allowed_for_self(store, cfg):
    store.upsert_reflection(
        Reflection(
            vault_id="default",
            text="open gap about timeline",
            status=ReflectionStatus.open,
            metadata={"domain": "technical", "sensitivity": "internal"},
        )
    )
    access = AccessRequest(
        audience="self",
        principal_id="owner",
        persona="individual",
        purpose="memory_retrieval",
        tool_id="test",
        requested_domains=["technical"],
    )
    pack = build_context_pack(
        store, cfg, HashEmbedder(),
        query="timeline",
        target_domain="technical",
        access=access,
    )
    assert any(r["text"] == "open gap about timeline" for r in pack.open_reflections)
    assert "Open Reflections" in (pack.context_pack or "")
