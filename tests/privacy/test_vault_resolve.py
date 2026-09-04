"""Active vault resolution."""

from __future__ import annotations

import os

from twin.privacy.models import Vault
from twin.privacy.vault import (
    FALLBACK_VAULT,
    iter_vault_ids,
    resolve_vault,
    set_active_vault,
    vault_display_name,
)


def test_resolve_vault_ignores_phantom_default(monkeypatch):
    monkeypatch.delenv("TWIN_VAULT", raising=False)
    assert resolve_vault("default") == FALLBACK_VAULT
    assert resolve_vault(None) == FALLBACK_VAULT


def test_resolve_vault_prefers_explicit_then_env(monkeypatch):
    monkeypatch.setenv("TWIN_VAULT", "vault_personal")
    assert resolve_vault("vault_dogfood") == "vault_dogfood"
    assert resolve_vault(None) == "vault_personal"


def test_resolve_vault_from_store_catalog(store, monkeypatch):
    monkeypatch.delenv("TWIN_VAULT", raising=False)
    store.insert_vault(Vault(id="vault_dogfood", name="Dogfood", source_owner="personal"))
    store.insert_vault(Vault(id="vault_personal", name="Personal", source_owner="personal"))
    assert "vault_personal" in iter_vault_ids(store)
    assert resolve_vault(None, store=store) == "vault_personal"


def test_vault_display_name_factory_and_custom():
    assert vault_display_name("vault_personal") == "Personal"
    assert vault_display_name("vault_general", "vault_general") == "General"
    assert vault_display_name("vault_work_acme") == "Work — acme"
    assert vault_display_name("vault_dogfood", "Dogfood") == "Dogfood"
    assert vault_display_name("vault_personal", "My life") == "My life"


def test_set_active_vault_persists(tmp_path, monkeypatch):
    monkeypatch.delenv("TWIN_VAULT", raising=False)
    vid = set_active_vault(tmp_path, "vault_dogfood")
    assert vid == "vault_dogfood"
    assert os.environ["TWIN_VAULT"] == "vault_dogfood"
    env = (tmp_path / "env").read_text(encoding="utf-8")
    assert "TWIN_VAULT=vault_dogfood" in env


def test_center_vaults_api(tmp_path, monkeypatch):
    monkeypatch.setenv("TWIN_HOME", str(tmp_path))
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    monkeypatch.setenv("TWIN_EXTRACTOR", "echo")
    monkeypatch.delenv("TWIN_VAULT", raising=False)

    from fastapi.testclient import TestClient

    from twin.interfaces.api import create_app
    from twin.privacy.models import Vault
    from twin.workspace import Workspace

    ws = Workspace(tmp_path)
    ws.store.insert_vault(Vault(id="vault_dogfood", name="Dogfood", source_owner="personal"))
    ws.store.insert_vault(Vault(id="vault_personal", name="vault_personal", source_owner="personal"))
    ws.close()
    client = TestClient(create_app(str(tmp_path)))
    listed = client.get("/api/center/vaults").json()
    assert listed["count"] >= 1
    by_id = {v["id"]: v["name"] for v in listed["vaults"]}
    assert by_id["vault_dogfood"] == "Dogfood"
    assert by_id["vault_personal"] == "Personal"
    put = client.put("/api/center/vault", json={"vault_id": "vault_dogfood"})
    assert put.status_code == 200, put.text
    assert put.json()["active"] == "vault_dogfood"
    again = client.get("/api/center/vaults").json()
    assert again["active"] == "vault_dogfood"
