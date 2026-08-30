"""Review batches (twin.store.batches)."""

from twin import ids
from twin.store.batches import create_batch
from twin.store.models import StoreClaim


def _mem(store, embedder, **kw):
    base = dict(
        id=ids.claim_id(), type="fact", title="t", summary="s",
        domain="technical", confidence=0.9, status="confirmed",
        entities=["Twin"],
    )
    base.update(kw)
    mem = StoreClaim(**base)
    store.insert_claim(mem)
    store.store_embedding(
        mem.id, "claim", embedder.name,
        embedder.embed(f"{mem.title}\n{mem.summary}"),
    )
    return mem


def test_review_batch_create(store, embedder):
    _mem(store, embedder, title="c1", summary="candidate one",
         status="candidate", needs_review=True)
    batch = create_batch(store, "July git", query={"status": "candidate", "needs_review": True})
    assert batch.progress_total >= 1
    assert store.get_review_batch(batch.id) is not None
