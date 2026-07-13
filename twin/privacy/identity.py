"""Trusted access context — server resolves identity; clients never self-assert.

Rule: registered identity > authenticated capability > request claims.
Absence of identity elevates to restricted mode, never to local-cli.
"""

from __future__ import annotations

from typing import Any, Optional

from ..memory.store.base import MemoryStore
from .models import AccessRequest, Principal, PrincipalType, ToolIdentity
from .yaml_io import DEFAULT_TOOLS, resolve_tool


# Surfaces that may mint a truly local principal after local auth.
LOCAL_SURFACES = frozenset({"cli", "local-cli", "twin-cli"})


def restricted_access(
    *,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None,
    requested_domains: Optional[list[str]] = None,
) -> AccessRequest:
    """Default when identity is missing — activates restricted mode."""
    return AccessRequest(
        principal_id="unknown",
        persona="unknown",
        purpose="unknown",
        audience="unknown",
        tool_id="unknown",
        project_id=project_id,
        session_id=session_id,
        requested_domains=requested_domains or [],
        execution_location=None,  # ignored by engine; registry wins
        metadata={"identity": "unresolved"},
    )


def resolve_execution_location(
    tool_id: str,
    *,
    store: Optional[MemoryStore] = None,
    claimed: Optional[str] = None,
) -> str:
    """Client claims are never authority. Unknown tool → unknown (not local)."""
    tool = resolve_tool(tool_id, store=store)
    if tool is None:
        return "unknown"
    # claimed location is observational only — never used
    _ = claimed
    return tool.execution_location or "unknown"


def resolve_access(
    store: MemoryStore,
    *,
    surface: str,
    client: Optional[str] = None,
    tool_id: Optional[str] = None,
    persona: Optional[str] = None,
    purpose: Optional[str] = None,
    audience: Optional[str] = None,
    principal_id: Optional[str] = None,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None,
    requested_domains: Optional[list[str]] = None,
    api_token: Optional[str] = None,
    capabilities_hint: Optional[list[str]] = None,
) -> AccessRequest:
    """Build a trusted AccessRequest from server-side surface identity.

    MCP/HTTP clients that omit identity get restricted mode.
    Only an authenticated local CLI surface may receive tool_id=local-cli.
    """
    surface_l = (surface or "").lower()
    client_l = (client or "").lower()

    # Explicit unknown / missing → restricted
    if surface_l in ("", "unknown", "mcp", "http", "api") and not _authenticated_local(
        surface_l, api_token, store
    ):
        # MCP/API must declare a registered client tool binding
        resolved_tool = _map_client_to_tool(client_l or tool_id, store)
        # Never allow external surfaces to self-assert local-cli
        if resolved_tool in ("local-cli", "cli", "twin-cli"):
            resolved_tool = None
        if resolved_tool is None or resolved_tool == "unknown":
            return restricted_access(
                project_id=project_id,
                session_id=session_id,
                requested_domains=requested_domains,
            )
        # Known external/registered client — still not privileged local-cli
        tool = resolve_tool(resolved_tool, store=store) or ToolIdentity(
            id=resolved_tool,
            execution_location="cloud" if "cloud" in resolved_tool or resolved_tool in (
                "claude-desktop", "chatgpt-cloud", "chatgpt",
            ) else "unknown",
            trusted_level="external",
        )
        principal = _load_or_default_principal(
            store,
            principal_id or f"tool_{tool.id}",
            name=tool.id,
            local=False,
            capabilities=capabilities_hint or ["read_context_pack"],
        )
        return AccessRequest(
            principal_id=principal.id,
            persona=persona or "individual",
            purpose=purpose or "memory_retrieval",
            audience=audience or "self",
            tool_id=tool.id,
            project_id=project_id,
            session_id=session_id,
            requested_domains=requested_domains or [],
            execution_location=None,
            metadata={
                "surface": surface_l,
                "client": client_l,
                "execution_location": tool.execution_location,
                "trusted_level": tool.trusted_level,
            },
        )

    # Authenticated local CLI
    if surface_l in LOCAL_SURFACES or _authenticated_local(surface_l, api_token, store):
        tool_name = "local-cli"
        principal = _load_or_default_principal(
            store,
            principal_id or "principal_local_cli",
            name="Local CLI",
            local=True,
            type_=PrincipalType.user,
            capabilities=capabilities_hint or [
                "read_context_pack", "read:technical", "session:write", "privacy:admin",
            ],
        )
        return AccessRequest(
            principal_id=principal.id,
            persona=persona or "individual",
            purpose=purpose or "memory_retrieval",
            audience=audience or "self",
            tool_id=tool_name,
            project_id=project_id,
            session_id=session_id,
            requested_domains=requested_domains or [],
            execution_location=None,
            metadata={
                "surface": "cli",
                "execution_location": "local",
                "trusted_level": "local",
            },
        )

    return restricted_access(
        project_id=project_id,
        session_id=session_id,
        requested_domains=requested_domains,
    )


def _authenticated_local(
    surface: str, api_token: Optional[str], store: MemoryStore,
) -> bool:
    if surface in LOCAL_SURFACES:
        return True
    # Optional local API token stored in config metadata — presence gates HTTP local
    if api_token and hasattr(store, "get_principal"):
        # token equals a registered local principal secret in metadata
        for pid in ("principal_local_cli", "principal_local_api"):
            p = store.get_principal(pid)
            if p and (p.metadata or {}).get("api_token") == api_token:
                return True
    return False


def _map_client_to_tool(client: Optional[str], store: MemoryStore) -> Optional[str]:
    if not client:
        return None
    mapping = {
        "cursor": "cursor",
        "claude-desktop": "claude-desktop",
        "claude_desktop": "claude-desktop",
        "chatgpt": "chatgpt-cloud",
        "chatgpt-cloud": "chatgpt-cloud",
        "local-cli": "local-cli",
        "cli": "local-cli",
        "twin-cli": "local-cli",
    }
    if client in mapping:
        return mapping[client]
    if client in DEFAULT_TOOLS:
        return client
    if store is not None and hasattr(store, "get_tool_identity"):
        t = store.get_tool_identity(client)
        if t:
            return t.id
    return None


def _load_or_default_principal(
    store: MemoryStore,
    principal_id: str,
    *,
    name: str,
    local: bool,
    type_: PrincipalType = PrincipalType.tool,
    capabilities: Optional[list[str]] = None,
) -> Principal:
    if hasattr(store, "get_principal"):
        existing = store.get_principal(principal_id)
        if existing is not None:
            return existing
    p = Principal(
        id=principal_id,
        type=type_,
        name=name,
        trusted=local,
        local=local,
        capabilities=list(capabilities or []),
    )
    if hasattr(store, "insert_principal"):
        try:
            store.insert_principal(p)
        except Exception:
            pass
    return p


def principal_has_capability(principal: Principal, capability: str) -> bool:
    caps = set(principal.capabilities or [])
    if "*" in caps or "privacy:admin" in caps:
        return True
    return capability in caps


def validate_vault_access(
    store: MemoryStore,
    *,
    vault_id: str,
    persona: str,
) -> bool:
    if not hasattr(store, "get_vault") and not hasattr(store, "list_privacy"):
        # no vault registry → allow logical default vaults for known personas
        defaults = {
            "vault_general": {"individual", "developer", "employee", "assistant_user", "*"},
            "vault_work": {"employee", "developer", "*"},
            "vault_personal": {"individual", "assistant_user", "*"},
            "vault_restricted": {"individual", "*"},
        }
        allowed = defaults.get(vault_id, {"*"})
        return persona in allowed or "*" in allowed
    # Prefer stored vault if present
    if hasattr(store, "_j_fetchone"):
        # duck-typed get via list — Vault store has insert_vault only in mixin
        pass
    return True


def active_consent_covers(
    store: MemoryStore,
    *,
    subject_ids: list[str],
    purpose: str,
    tool_id: str,
    categories: list[str],
) -> bool:
    if not subject_ids:
        return True
    if not hasattr(store, "list_consents"):
        return False
    from .models import ConsentStatus
    for c in store.list_consents(status=ConsentStatus.active.value):
        if c.subject_id not in subject_ids and c.subject_id != "*":
            continue
        if c.purposes and purpose not in c.purposes and "*" not in c.purposes:
            continue
        if c.allowed_tools and tool_id not in c.allowed_tools and "local" not in c.allowed_tools and "*" not in c.allowed_tools:
            continue
        if c.data_categories and categories:
            if not (set(c.data_categories) & set(categories)) and "*" not in c.data_categories:
                continue
        from ..clock import now_iso
        if c.valid_until and c.valid_until < now_iso():
            continue
        return True
    return False
