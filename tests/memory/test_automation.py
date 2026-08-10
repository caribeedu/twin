"""Safe quality automation and batch apply (twin.store.automation)."""

from twin import ids
from twin.cognize.services.quality import (
    analyze_memory,
    build_duplicate_groups,
    select_canonical_survivor,
)
from twin.store.automation import apply_safe_automations, batch_apply, batch_preview
from twin.store.models import MemoryItem, MemoryStatus


def _mem(store, embedder, **kw):
    base = dict(
        id=ids.memory_id(), type="fact", title="t", summary="s",
        domain="technical", confidence=0.9, status="confirmed",
        entities=["Twin"], project_id="proj_twin",
    )
    base.update(kw)
    mem = MemoryItem(**base)
    store.insert_memory(mem)
    store.store_embedding(
        mem.id, "memory", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def test_batch_preview_blocks_sensitive(store, embedder):
    m = _mem(store, embedder, title="private belief", summary="sensitive opinion",
             type="belief", status="candidate", sensitivity="private", needs_review=True)
    preview = batch_preview(store, [m.id], "confirm")
    assert preview["requires_individual_review"]
    assert preview["preview_token"]
    missing = batch_apply(store, [m.id], "confirm", force=False)
    assert missing["applied"] == 0
    assert missing["error"] == "preview_token_required"
    result = batch_apply(
        store, [m.id], "confirm", force=False, preview_token=preview["preview_token"],
    )
    assert result["applied"] == 0
    assert result["error"] == "requires_individual_review"


def test_preview_token_detects_state_change(store, embedder):
    m = _mem(
        store, embedder, title="note", summary="stable text",
        status="candidate", needs_review=True, sensitivity="public", type="fact",
    )
    preview = batch_preview(store, [m.id], "confirm")
    token = preview["preview_token"]
    assert not preview["requires_individual_review"]

    missing = batch_apply(store, [m.id], "confirm")
    assert missing["error"] == "preview_token_required"

    store.update_memory(m.id, summary="changed after preview")
    stale = batch_apply(store, [m.id], "confirm", preview_token=token)
    assert stale["applied"] == 0
    assert stale["error"] == "preview_token_mismatch"

    fresh = batch_preview(store, [m.id], "confirm")
    ok = batch_apply(store, [m.id], "confirm", preview_token=fresh["preview_token"])
    assert ok["applied"] == 1
    assert store.get_memory(m.id).status == MemoryStatus.confirmed


def test_exact_duplicate_keeps_one_survivor(store, embedder):
    a = _mem(store, embedder, title="Same", summary="Same claim text.",
             status="candidate", needs_review=True, confidence=0.7,
             quality_flags=["exact_duplicate"])
    b = _mem(store, embedder, title="Same", summary="Same claim text.",
             status="candidate", needs_review=True, confidence=0.9,
             quality_flags=["exact_duplicate"])
    c = _mem(store, embedder, title="Same", summary="Same claim text.",
             status="confirmed", confidence=0.8,
             quality_flags=["exact_duplicate"])
    analyze_memory(store, embedder, a.id)
    analyze_memory(store, embedder, b.id)
    analyze_memory(store, embedder, c.id)
    for m in (a, b, c):
        store.update_memory(m.id, quality_flags=["exact_duplicate"])

    groups = build_duplicate_groups(store, [
        store.get_memory(a.id), store.get_memory(b.id), store.get_memory(c.id),
    ])
    assert groups
    survivor = select_canonical_survivor(
        [store.get_memory(x) for x in groups[0].memory_ids], store,
    )
    assert survivor.id == c.id

    apply_safe_automations(store, dry_run=False)
    rejected = sum(
        1 for mid in (a.id, b.id, c.id)
        if store.get_memory(mid).status == MemoryStatus.rejected
    )
    assert rejected == 2
    assert store.get_memory(c.id).status != MemoryStatus.rejected
