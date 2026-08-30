"""MCP process identity — env only, never tool-call arguments.

Hosts (Claude Code, Cursor, …) must put credentials in the MCP server
``env`` block. The model cannot supply or override ``client`` /
``client_token`` on tool calls.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Optional

from twin.privacy.identity import (
    ensure_local_identity,
    hash_credential,
    register_client_binding,
    resolve_access,
)
from twin.privacy.models import ClientBinding, Principal, PrincipalType
from twin.privacy.yaml_io import bootstrap_policy_set

MCP_CLIENT_ENV = "TWIN_MCP_CLIENT"
MCP_TOKEN_ENV = "TWIN_MCP_CLIENT_TOKEN"

# Personal IDE clients — read packs + session write; not local-cli.
DEFAULT_MCP_CAPABILITIES = [
    "read_context_pack",
    "read:domain:technical",
    "read:domain:work",
    "read:domain:finance",
    "read:domain:personal_preferences",
    "read:domain:assistant_preferences",
    "read:vault:vault_general",
    "read:vault:vault_work",
    "read:vault:vault_personal",
    "read:vault:vault_restricted",
    "session:write",
    "connector:read",
    "connector:backfill",
]

DEFAULT_MCP_PERSONAS = [
    "individual", "developer", "employee", "assistant_user",
    "tech_lead", "personal_project_builder", "private_individual", "global",
]

DEFAULT_MCP_VAULTS = [
    "vault_general", "vault_work", "vault_personal", "vault_restricted",
]


def mcp_process_identity() -> tuple[Optional[str], Optional[str]]:
    """Return ``(client_id, token)`` from process env. Empty → restricted."""
    client = (os.environ.get(MCP_CLIENT_ENV) or "").strip() or None
    token = (os.environ.get(MCP_TOKEN_ENV) or "").strip() or None
    return client, token


def resolve_mcp_access(
    store,
    *,
    persona: str = "individual",
    purpose: str = "context_retrieval",
    audience: str = "self",
    project_id: Optional[str] = None,
    session_id: Optional[str] = None,
    requested_domains: Optional[list[str]] = None,
):
    """Build AccessRequest for this MCP process from env credentials only."""
    client, token = mcp_process_identity()
    return resolve_access(
        store,
        surface="mcp",
        client=client,
        api_token=token,
        persona=persona,
        purpose=purpose,
        audience=audience,
        project_id=project_id,
        session_id=session_id,
        requested_domains=requested_domains,
    )


def mcp_client_token_path(home: Path, client_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in client_id)
    return Path(home) / "secrets" / "mcp" / f"{safe}.token"


def load_or_create_mcp_token(home: Path, client_id: str) -> str:
    path = mcp_client_token_path(home, client_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        text = path.read_text(encoding="utf-8").strip()
        if text:
            return text
    token = secrets.token_urlsafe(32)
    path.write_text(token + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


def ensure_mcp_client_binding(
    store,
    *,
    client_id: str,
    credential: str,
    home: Optional[Path] = None,
    policies_path: Optional[Path] = None,
) -> ClientBinding:
    """Provision or rotate the ClientBinding for an IDE MCP host."""
    if policies_path is not None:
        bootstrap_policy_set(store, policies_path=policies_path)
    else:
        bootstrap_policy_set(store)
    ensure_local_identity(store)

    principal_id = f"principal_mcp_{client_id}".replace("-", "_")
    principal = store.get_principal(principal_id) if hasattr(store, "get_principal") else None
    if principal is None:
        store.insert_principal(Principal(
            id=principal_id,
            type=PrincipalType.tool,
            name=client_id,
            capabilities=list(DEFAULT_MCP_CAPABILITIES),
            allowed_personas=list(DEFAULT_MCP_PERSONAS),
            allowed_vaults=list(DEFAULT_MCP_VAULTS),
            allowed_purposes=["*", "context_retrieval", "task_execution", "debugging"],
            allowed_audiences=["self", "local"],
        ))

    existing = store.get_client_binding_by_client(client_id)
    if existing is None:
        return register_client_binding(
            store,
            client_id=client_id,
            tool_id=client_id,
            principal_id=principal_id,
            credential=credential,
            authentication_mode="credential",
            capabilities=list(DEFAULT_MCP_CAPABILITIES),
            allowed_personas=list(DEFAULT_MCP_PERSONAS),
            allowed_vaults=list(DEFAULT_MCP_VAULTS),
            allowed_purposes=["*", "context_retrieval", "task_execution", "debugging"],
            allowed_audiences=["self", "local"],
        )

    # Rotate credential + refresh allowlists on re-setup.
    updated = existing.model_copy(update={
        "credential_hash": hash_credential(credential),
        "principal_id": principal_id,
        "tool_id": client_id,
        "capabilities": list(DEFAULT_MCP_CAPABILITIES),
        "allowed_personas": list(DEFAULT_MCP_PERSONAS),
        "allowed_vaults": list(DEFAULT_MCP_VAULTS),
        "metadata": {
            **(existing.metadata or {}),
            "authentication_mode": "credential",
        },
    })
    store.update_client_binding(updated)
    return updated


def provision_mcp_client(store, home: Path, client_id: str, *,
                         policies_path: Optional[Path] = None) -> dict[str, str]:
    """Ensure binding + durable token; return env vars for the MCP config."""
    token = load_or_create_mcp_token(home, client_id)
    ensure_mcp_client_binding(
        store, client_id=client_id, credential=token,
        home=home, policies_path=policies_path,
    )
    return {
        MCP_CLIENT_ENV: client_id,
        MCP_TOKEN_ENV: token,
    }
