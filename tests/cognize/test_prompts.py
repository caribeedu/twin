"""Owner purpose block for Cognize judgment stages."""

from __future__ import annotations

from twin.cognize.prompts import judgment_purpose, owner_aliases
from twin.sense.connectors.models import SourceAccount


def test_owner_aliases_from_source_account(store):
    store.insert_source_account(SourceAccount(
        connector_type="github",
        external_account_id="caribeedu",
        display_name="Edu",
        owner_principal_id="prin_test",
        vault_id="vault_general",
    ))
    aliases = owner_aliases(store, "vault_general")
    assert "Edu" in aliases
    assert any("caribeedu" in a for a in aliases)
    other = owner_aliases(store, "vault_work")
    assert other == []
    block = judgment_purpose(store, "vault_general")
    assert "caribeedu" in block or "Edu" in block
    assert "account owner" in block.lower() or "Owner identity" in block


def test_judgment_purpose_without_accounts(store):
    block = judgment_purpose(store, "vault_personal")
    assert "unknown this run" in block
    assert "zero" in block.lower() or "fewer items" in block
