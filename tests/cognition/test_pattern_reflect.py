"""Pattern reflection — nightly window mining into preference/procedure candidates.

The model is simulated via ``set_pattern_override``; without a reflector the
pass defers (no lexical fallback).
"""

from __future__ import annotations

import pytest

from twin.cognize.services.episode_reflect import TrajectoryClaim
from twin.cognize.services.pattern_reflect import pattern_reflect, set_pattern_override
from twin.sense.connectors.models import (
    ConnectorInstance,
    ConnectorStatus,
    ConnectorRecord,
    OwnershipClass,
    SourceAccount,
    idempotency_key,
)
from twin.store.models import MemoryStatus, MemoryType


@pytest.fixture(autouse=True)
def _reset_pattern_override():
    set_pattern_override(None)
    yield
    set_pattern_override(None)


def _acct(store, *, vault_id="vault_work_acme", account_id="acct_pat"):
    acc = SourceAccount(
        id=account_id, connector_type="github",
        external_account_id=account_id, owner_principal_id="p1",
        source_owner=OwnershipClass.employer, vault_id=vault_id, org_key="acme",
    )
    store.insert_source_account(acc)
    inst = ConnectorInstance(
        id=f"conn_{account_id}", connector_type="github",
        account_id=acc.id, status=ConnectorStatus.active,
    )
    store.insert_connector_instance(inst)
    return acc, inst


def _rec(**kwargs) -> ConnectorRecord:
    defaults = dict(
        connector_id="conn_1", source_account_id="acct_1",
        external_type="commit", external_id="c1", external_revision="1",
        content="hello", source_metadata={}, ownership={},
    )
    defaults.update(kwargs)
    rec = ConnectorRecord(**defaults)
    if not rec.idempotency_key:
        rec.idempotency_key = idempotency_key(
            "test", rec.source_account_id, rec.external_type,
            rec.external_id, rec.external_revision,
        )
    return rec


def _seed_style_window(store, acc, inst, *, n=3):
    for i in range(n):
        store.insert_connector_record(_rec(
            id=f"style_{i}", connector_id=inst.id, source_account_id=acc.id,
            external_type="commit", external_id=f"sha{i}",
            content=f"Refactor module {i}: drop parentheses on if guards, "
                    f"keep it DRY by extracting the shared validator.",
            occurred_at=f"2026-07-1{i}T09:00:00Z",
            ownership={"vault_id": acc.vault_id},
            source_metadata={"provider": "github", "repo": "acme/atlas"},
        ))


def _style_reflector(dossier, cfg):
    return [TrajectoryClaim(
        type="preference",
        domain="technical",
        title="Prefers parenthesis-free if guards",
        summary="Across commits Edu consistently drops parentheses on if "
                "guards and extracts shared validators for DRY.",
        evidence_quotes=["drop parentheses on if guards"],
        valid_from=dossier.focus.time_from,
        twin_influenced=True,
    )]


def test_pattern_reflect_creates_preference_candidate(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_style")
    _seed_style_window(store, acc, inst)
    set_pattern_override(_style_reflector)

    res = pattern_reflect(
        store, cfg, embedder,
        vault_id=acc.vault_id,
        time_from="2026-07-01T00:00:00Z", time_until="2026-07-31T23:59:59Z",
    )
    assert res.claims, res.skipped_reason
    mem = store.get_memory(res.claims[0]["memory_id"])
    assert mem is not None
    assert mem.status == MemoryStatus.candidate
    assert mem.needs_review is True
    assert mem.review_reason == "pattern_reflect"
    assert mem.type == MemoryType.preference
    assert mem.payload.get("source") == "pattern_reflect"
    assert mem.payload.get("pattern") is True


def test_pattern_reflect_requires_min_signals(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_one")
    _seed_style_window(store, acc, inst, n=1)
    set_pattern_override(_style_reflector)
    res = pattern_reflect(
        store, cfg, embedder,
        vault_id=acc.vault_id,
        time_from="2026-07-01T00:00:00Z", time_until="2026-07-31T23:59:59Z",
    )
    assert res.claims == []
    assert "not enough signal" in res.skipped_reason


def test_pattern_reflect_defers_without_model(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_defer")
    _seed_style_window(store, acc, inst)
    # echo extractor + no override → defer, never fabricate
    res = pattern_reflect(
        store, cfg, embedder,
        vault_id=acc.vault_id,
        time_from="2026-07-01T00:00:00Z", time_until="2026-07-31T23:59:59Z",
    )
    assert res.claims == []
    assert "deferred" in res.skipped_reason.lower()


def test_pattern_reflect_is_idempotent(store, cfg, embedder):
    acc, inst = _acct(store, account_id="acct_idem2")
    _seed_style_window(store, acc, inst)
    set_pattern_override(_style_reflector)
    first = pattern_reflect(
        store, cfg, embedder, vault_id=acc.vault_id,
        time_from="2026-07-01T00:00:00Z", time_until="2026-07-31T23:59:59Z",
    )
    ids_first = {c["memory_id"] for c in first.claims}
    second = pattern_reflect(
        store, cfg, embedder, vault_id=acc.vault_id,
        time_from="2026-07-01T00:00:00Z", time_until="2026-07-31T23:59:59Z",
    )
    for c in second.claims:
        assert c["memory_id"] in ids_first
        assert c["created"] is False
