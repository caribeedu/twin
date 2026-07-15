"""Connector surfaces demand connector:* capabilities (MCP + HTTP API).

Invariants under test:

    read_context_pack  does NOT imply  connector:read
    connector:read     does NOT imply  connector:sync
    connector:sync on one vault does NOT imply another vault
    confirm=true is state-aware (fingerprint token, not a boolean)
    accounts created over the API belong to the resolved principal
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from twin.connectors import (
    add_connector_instance,
    build_credential_store,
    register_source_account,
)

READER_TOKEN = "tok-reader"
SYNCER_TOKEN = "tok-syncer"
PACK_ONLY_TOKEN = "tok-packonly"


def _bootstrap_identity(store):
    from twin.privacy.identity import ensure_local_identity, register_client_binding
    from twin.privacy.models import Principal, PrincipalType
    from twin.privacy.yaml_io import bootstrap_policy_set

    bootstrap_policy_set(store)
    ensure_local_identity(store)

    def principal(pid, caps, vaults):
        store.insert_principal(Principal(
            id=pid, type=PrincipalType.tool, name=pid,
            capabilities=caps,
            allowed_personas=["individual", "developer"],
            allowed_vaults=vaults,
        ))

    principal("principal_conn_reader", ["connector:read"],
              ["vault_general", "vault_personal"])
    principal("principal_conn_syncer", ["connector:read", "connector:sync"],
              ["vault_general", "vault_personal"])
    principal("principal_pack_only", ["read_context_pack"],
              ["vault_general", "vault_personal"])

    def binding(client, pid, token, caps, vaults):
        register_client_binding(
            store, client_id=client, tool_id=client, principal_id=pid,
            credential=token, capabilities=caps,
            allowed_personas=["individual", "developer"],
            allowed_vaults=vaults,
        )

    binding("conn-reader", "principal_conn_reader", READER_TOKEN,
            ["connector:read"], ["vault_general", "vault_personal"])
    binding("conn-syncer", "principal_conn_syncer", SYNCER_TOKEN,
            ["connector:read", "connector:sync"],
            ["vault_general", "vault_personal"])
    binding("pack-only", "principal_pack_only", PACK_ONLY_TOKEN,
            ["read_context_pack"], ["vault_general", "vault_personal"])


def _make_connector(home: str):
    from twin.workspace import Workspace

    ws = Workspace(home)
    _bootstrap_identity(ws.store)
    creds = build_credential_store(Path(home))
    acc = register_source_account(
        ws.store, connector_type="fake", source_owner="personal",
        owner_principal_id="principal_conn_syncer",
    )
    inst = add_connector_instance(ws.store, creds, account_id=acc.id,
                                  secret="tok-conn")
    ws.close()
    return acc, inst


async def _call(server, tool, args):
    result = await server.call_tool(tool, args)
    return json.loads(result[0][0].text)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.mark.anyio
async def test_mcp_connector_tools_require_identity_and_capability(tmp_path, monkeypatch):
    from twin.interfaces.mcp_server import create_server

    monkeypatch.setenv("TWIN_EXTRACTOR", "heuristic")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    home = str(tmp_path / "twin-home")
    _acc, inst = _make_connector(home)
    server = create_server(home)

    # anonymous / unresolved identity → denied, even for reads
    for tool, args in (
        ("connector_list", {}),
        ("connector_status", {"connector_id": inst.id}),
        ("connector_health_all", {}),
        ("connector_dead_letters", {"connector_id": inst.id}),
    ):
        out = await _call(server, tool, args)
        assert out.get("error") == "not_authorized", tool

    # read_context_pack does NOT imply connector:read
    out = await _call(server, "connector_list", {
        "client": "pack-only", "client_token": PACK_ONLY_TOKEN,
    })
    assert out.get("error") == "not_authorized"

    # connector:read sees the connector…
    listed = await _call(server, "connector_list", {
        "client": "conn-reader", "client_token": READER_TOKEN,
    })
    assert [c["connector_id"] for c in listed] == [inst.id]
    status = await _call(server, "connector_status", {
        "connector_id": inst.id,
        "client": "conn-reader", "client_token": READER_TOKEN,
    })
    assert status["connector_id"] == inst.id

    # …but connector:read does NOT imply connector:sync
    denied = await _call(server, "connector_sync", {
        "connector_id": inst.id, "confirm": True,
        "client": "conn-reader", "client_token": READER_TOKEN,
    })
    assert denied.get("error") == "not_authorized"
    assert "connector:sync" in denied["reason"]


@pytest.mark.anyio
async def test_mcp_connector_sync_confirm_token_is_state_aware(tmp_path, monkeypatch):
    from twin.interfaces.mcp_server import create_server
    from twin.workspace import Workspace

    monkeypatch.setenv("TWIN_EXTRACTOR", "heuristic")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    home = str(tmp_path / "twin-home")
    _acc, inst = _make_connector(home)
    server = create_server(home)
    ident = {"client": "conn-syncer", "client_token": SYNCER_TOKEN}

    # confirm=true without a token from a preview is refused
    blind = await _call(server, "connector_sync", {
        "connector_id": inst.id, "confirm": True, **ident,
    })
    assert blind.get("error") == "stale_preview"

    preview = await _call(server, "connector_sync", {
        "connector_id": inst.id, **ident,
    })
    assert preview["requires_confirmation"] is True
    token = preview["confirm_token"]

    # the connector changes between preview and apply → token no longer valid
    ws = Workspace(home)
    ws.store.update_connector_instance(inst.id, configuration={"changed": True})
    ws.close()
    stale = await _call(server, "connector_sync", {
        "connector_id": inst.id, "confirm": True, "confirm_token": token, **ident,
    })
    assert stale.get("error") == "stale_preview"

    # fresh preview against the current state executes
    fresh = await _call(server, "connector_sync", {"connector_id": inst.id, **ident})
    done = await _call(server, "connector_sync", {
        "connector_id": inst.id, "confirm": True,
        "confirm_token": fresh["confirm_token"], **ident,
    })
    assert done["health"] == "healthy"
    assert done["percepts"] == 3


def test_api_connector_endpoints_require_capabilities(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from twin.interfaces.api import create_app

    monkeypatch.setenv("TWIN_EXTRACTOR", "heuristic")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    home = str(tmp_path / "twin-home")
    _acc, inst = _make_connector(home)
    client = TestClient(create_app(home=home))

    reader = {"x-twin-client": "conn-reader", "x-twin-token": READER_TOKEN}
    syncer = {"x-twin-client": "conn-syncer", "x-twin-token": SYNCER_TOKEN}
    pack_only = {"x-twin-client": "pack-only", "x-twin-token": PACK_ONLY_TOKEN}

    # no identity → 403 on every connector surface
    assert client.get("/api/connectors").status_code == 403
    assert client.get(f"/api/connectors/{inst.id}").status_code == 403
    assert client.post(f"/api/connectors/{inst.id}/sync", json={}).status_code == 403
    assert client.post(f"/api/connectors/{inst.id}/revoke").status_code == 403
    assert client.post("/api/connectors", json={
        "connector_type": "fake", "source_owner": "personal",
    }).status_code == 403

    # global read capability does not open connector administration
    assert client.get("/api/connectors", headers=pack_only).status_code == 403

    # connector:read reads, but cannot sync/pause/revoke/configure
    assert client.get("/api/connectors", headers=reader).status_code == 200
    assert client.get(f"/api/connectors/{inst.id}/checkpoints",
                      headers=reader).status_code == 200
    assert client.get(f"/api/connectors/{inst.id}/dead-letters",
                      headers=reader).status_code == 200
    assert client.post(f"/api/connectors/{inst.id}/sync", json={},
                       headers=reader).status_code == 403
    assert client.post(f"/api/connectors/{inst.id}/pause",
                       headers=reader).status_code == 403
    assert client.post(f"/api/connectors/{inst.id}/revoke",
                       headers=reader).status_code == 403
    assert client.post("/api/connectors", json={
        "connector_type": "fake", "source_owner": "personal",
    }, headers=reader).status_code == 403

    # connector:sync executes the sync
    r = client.post(f"/api/connectors/{inst.id}/sync", json={}, headers=syncer)
    assert r.status_code == 200
    assert r.json()["percepts"] == 3


def test_api_connector_add_binds_to_resolved_principal(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient

    from twin.interfaces.api import create_app
    from twin.privacy.identity import register_client_binding
    from twin.privacy.models import Principal, PrincipalType
    from twin.workspace import Workspace

    monkeypatch.setenv("TWIN_EXTRACTOR", "heuristic")
    monkeypatch.setenv("TWIN_EMBEDDER", "hash")
    home = str(tmp_path / "twin-home")

    ws = Workspace(home)
    _bootstrap_identity(ws.store)
    ws.store.insert_principal(Principal(
        id="principal_admin_tool", type=PrincipalType.tool, name="admin",
        capabilities=["connector:configure", "connector:credentials",
                      "connector:read"],
        allowed_personas=["individual"],
        allowed_vaults=["vault_general", "vault_personal"],
    ))
    register_client_binding(
        ws.store, client_id="admin-tool", tool_id="admin-tool",
        principal_id="principal_admin_tool", credential="tok-admin",
        capabilities=["connector:configure", "connector:credentials",
                      "connector:read"],
        allowed_personas=["individual"],
        allowed_vaults=["vault_general", "vault_personal"],
    )
    ws.close()

    client = TestClient(create_app(home=home))
    admin = {"x-twin-client": "admin-tool", "x-twin-token": "tok-admin"}
    r = client.post("/api/connectors", json={
        "connector_type": "fake", "source_owner": "personal",
        "secret": "tok-new",
    }, headers=admin)
    assert r.status_code == 200

    ws = Workspace(home)
    account = ws.store.get_source_account(r.json()["account_id"])
    # the account belongs to the resolved principal — never a default
    assert account.owner_principal_id == "principal_admin_tool"
    ws.close()
