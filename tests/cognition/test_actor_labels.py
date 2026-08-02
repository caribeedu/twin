"""Source-level @user / #channel rewriting."""
from __future__ import annotations

from twin.cognition.actor_labels import humanize_record_text, rewrite_labels
from twin.connectors.models import (
    ConnectorInstance, ConnectorRecord, ConnectorStatus, OwnershipClass,
    SourceAccount, idempotency_key,
)


def test_rewrite_labels_uses_at_and_hash():
    out = rewrite_labels(
        "Slack message in C0BM8DT14S2 by U0BMAC6T5EW: hi U0BMAC2RKR8",
        user_labels={"U0BMAC6T5EW": "John", "U0BMAC2RKR8": "Edu"},
        channel_labels={"C0BM8DT14S2": "#product"},
    )
    assert out == "Slack message in #product by @John: hi @Edu"
    assert "U0" not in out
    assert "C0" not in out


def test_humanize_record_reads_channel_metadata_cache(store):
    acc = SourceAccount(
        id="acc_sl_lbl", connector_type="slack",
        external_account_id="T1", owner_principal_id="p1",
        source_owner=OwnershipClass.personal, vault_id="vault_dogfood",
    )
    store.insert_source_account(acc)
    inst = ConnectorInstance(
        id="conn_sl_lbl", connector_type="slack", account_id=acc.id,
        status=ConnectorStatus.active,
        configuration={
            "channel_metadata": {"C0BM8DT14S2": {"name": "product"}},
        },
    )
    store.insert_connector_instance(inst)
    rec = ConnectorRecord(
        id="rec_sl_lbl",
        connector_id=inst.id,
        source_account_id=acc.id,
        external_type="message",
        external_id="C0BM8DT14S2:1",
        external_revision="1",
        content="Slack message in C0BM8DT14S2 by U0BMAC6T5EW:\nhello",
        actor_ids=["slack:T1:U0BMAC6T5EW"],
        ownership={"vault_id": "vault_dogfood"},
        source_metadata={
            "channel": "C0BM8DT14S2",
            "author_name": "John",
            "user_labels": {"U0BMAC6T5EW": "John"},
        },
        idempotency_key=idempotency_key(
            "test", acc.id, "message", "C0BM8DT14S2:1", "1",
        ),
    )
    store.insert_connector_record(rec)
    out = humanize_record_text(store, rec)
    assert "#product" in out
    assert "@John" in out
    assert "U0BMAC6T5EW" not in out
    assert "C0BM8DT14S2" not in out
