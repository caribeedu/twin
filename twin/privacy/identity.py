"""Trusted access context — server resolves identity; clients never self-assert.

Rule: registered binding > authenticated capability > request claims.
Absence of authenticated binding → restricted mode, never local-cli.
Known tool names alone never mint principals or capabilities.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from ..memory.store.base import MemoryStore
from .models import (
    AccessRequest,
    ClientBinding,
    Principal,
    PrincipalType,
    ToolIdentity,
    Vault,
)
from .yaml_io import DEFAULT_TOOLS, resolve_tool


LOCAL_SURFACES = frozenset({"cli", "local-cli", "twin-cli"})

# No wildcards — unknown persona on a vault is deny.
DEFAULT_VAULT_PERSONAS: dict[str, set[str]] = {
    "vault_general": {"individual", "developer", "employee", "assistant_user"},
    "vault_work": {"employee", "developer"},
    "vault_personal": {"individual", "assistant_user"},
    "vault_restricted": {"individual"},
}


def restricted_access(
    *,
    project_id: Optional[str] = None,
    session_id: Optional[str] = None,
    requested_domains: Optional[list[str]] = None,
    claims: Optional[dict[str, Any]] = None,
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
        execution_location=None,
        metadata={
            "identity": "unresolved",
            "claims": claims or {},
        },
    )


def resolve_execution_location(
    tool_id: str,
    *,
    store: Optional[MemoryStore] = None,
    claimed: Optional[str] = None,
) -> str:
    """Client claims are never authority. Unknown tool → unknown (not local)."""
    tool = resolve_tool(tool_id, store=store)
    _ = claimed
    if tool is None:
        return "unknown"
    return tool.execution_location or "unknown"


def hash_credential(token: str) -> str:
    return hashlib.sha256((token or "").encode()).hexdigest()


def register_client_binding(
    store: MemoryStore,
    *,
    client_id: str,
    tool_id: str,
    principal_id: str,
    credential: Optional[str] = None,
    capabilities: Optional[list[str]] = None,
    allowed_personas: Optional[list[str]] = None,
    allowed_purposes: Optional[list[str]] = None,
    allowed_audiences: Optional[list[str]] = None,
    allowed_vaults: Optional[list[str]] = None,
) -> ClientBinding:
    """Administrative provisioning — never called from a read path."""
    binding = ClientBinding(
        id=ids.new_id("cbind"),
        client_id=client_id,
        tool_id=tool_id,
        principal_id=principal_id,
        credential_hash=hash_credential(credential) if credential else None,
        capabilities=list(capabilities or []),
        allowed_personas=list(allowed_personas or ["individual"]),
        allowed_purposes=list(allowed_purposes or ["memory_retrieval", "task_execution", "*"]),
        allowed_audiences=list(allowed_audiences or ["self"]),
        allowed_vaults=list(allowed_vaults or ["vault_general"]),
        created_at=now_iso(),
    )
    store.insert_client_binding(binding)
    return binding


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
    """Build a trusted AccessRequest from authenticated binding or local CLI.

    Declaring ``client=cursor`` without a registered binding stays restricted.
    """
    _ = capabilities_hint  # never trusted from the wire
    surface_l = (surface or "").lower()
    client_l = (client or "").lower()
    claims = {
        "surface": surface_l,
        "client": client_l,
        "tool_id": tool_id,
        "persona": persona,
        "purpose": purpose,
        "audience": audience,
        "principal_id": principal_id,
    }

    # Authenticated local CLI surface — principal must already exist (bootstrap).
    if surface_l in LOCAL_SURFACES or _authenticated_local(surface_l, api_token, store):
        principal = None
        if hasattr(store, "get_principal"):
            principal = store.get_principal(principal_id or "principal_local_cli")
        if principal is None:
            return restricted_access(
                project_id=project_id, session_id=session_id,
                requested_domains=requested_domains, claims=claims,
            )
        resolved = _apply_allowlists(
            principal=principal,
            tool_id="local-cli",
            persona=persona,
            purpose=purpose,
            audience=audience,
            project_id=project_id,
            session_id=session_id,
            requested_domains=requested_domains,
            claims=claims,
            binding=None,
            extra_meta={"surface": "cli", "trusted_level": "local"},
        )
        return resolved

    # External / MCP / HTTP — require registered client binding (+ credential if set)
    binding = _find_binding(store, client_l or tool_id, api_token)
    if binding is None:
        return restricted_access(
            project_id=project_id, session_id=session_id,
            requested_domains=requested_domains, claims=claims,
        )
    if binding.tool_id in ("local-cli", "cli", "twin-cli") and surface_l not in LOCAL_SURFACES:
        return restricted_access(
            project_id=project_id, session_id=session_id,
            requested_domains=requested_domains, claims=claims,
        )
    principal = store.get_principal(binding.principal_id) if hasattr(store, "get_principal") else None
    if principal is None:
        return restricted_access(
            project_id=project_id, session_id=session_id,
            requested_domains=requested_domains, claims=claims,
        )
    return _apply_allowlists(
        principal=principal,
        tool_id=binding.tool_id,
        persona=persona,
        purpose=purpose,
        audience=audience,
        project_id=project_id,
        session_id=session_id,
        requested_domains=requested_domains,
        claims=claims,
        binding=binding,
        extra_meta={
            "surface": surface_l,
            "client_binding_id": binding.id,
            "trusted_level": (resolve_tool(binding.tool_id, store=store) or ToolIdentity(
                id=binding.tool_id, execution_location="unknown",
            )).trusted_level,
        },
    )


def _find_binding(
    store: MemoryStore,
    client_key: Optional[str],
    api_token: Optional[str],
) -> Optional[ClientBinding]:
    if not client_key or not hasattr(store, "get_client_binding_by_client"):
        return None
    binding = store.get_client_binding_by_client(client_key)
    if binding is None or binding.revoked_at:
        return None
    if binding.credential_hash:
        if not api_token or hash_credential(api_token) != binding.credential_hash:
            return None
    return binding


def _apply_allowlists(
    *,
    principal: Principal,
    tool_id: str,
    persona: Optional[str],
    purpose: Optional[str],
    audience: Optional[str],
    project_id: Optional[str],
    session_id: Optional[str],
    requested_domains: Optional[list[str]],
    claims: dict[str, Any],
    binding: Optional[ClientBinding],
    extra_meta: dict[str, Any],
) -> AccessRequest:
    allowed_personas = list(
        (binding.allowed_personas if binding and binding.allowed_personas else None)
        or principal.allowed_personas
        or (["individual"] if principal.local else [])
    )
    allowed_purposes = list(
        (binding.allowed_purposes if binding and binding.allowed_purposes else None)
        or principal.allowed_purposes
        or ["memory_retrieval", "task_execution"]
    )
    allowed_audiences = list(
        (binding.allowed_audiences if binding and binding.allowed_audiences else None)
        or principal.allowed_audiences
        or ["self"]
    )
    requested_persona = persona or (allowed_personas[0] if allowed_personas else "unknown")
    requested_purpose = purpose or "memory_retrieval"
    requested_audience = audience or "self"

    if allowed_personas and requested_persona not in allowed_personas and "*" not in allowed_personas:
        return restricted_access(
            project_id=project_id, session_id=session_id,
            requested_domains=requested_domains, claims=claims,
        )
    if (
        allowed_purposes
        and requested_purpose not in allowed_purposes
        and "*" not in allowed_purposes
    ):
        return restricted_access(
            project_id=project_id, session_id=session_id,
            requested_domains=requested_domains, claims=claims,
        )
    if (
        allowed_audiences
        and requested_audience not in allowed_audiences
        and "*" not in allowed_audiences
    ):
        return restricted_access(
            project_id=project_id, session_id=session_id,
            requested_domains=requested_domains, claims=claims,
        )

    caps = list(binding.capabilities if binding and binding.capabilities else principal.capabilities)
    return AccessRequest(
        principal_id=principal.id,
        persona=requested_persona,
        purpose=requested_purpose,
        audience=requested_audience,
        tool_id=tool_id,
        project_id=project_id,
        session_id=session_id,
        requested_domains=requested_domains or [],
        execution_location=None,
        metadata={
            **extra_meta,
            "claims": claims,
            "resolved_capabilities": caps,
            "allowed_personas": allowed_personas,
            "allowed_vaults": list(
                (binding.allowed_vaults if binding and binding.allowed_vaults else None)
                or principal.allowed_vaults
                or []
            ),
        },
    )


def _authenticated_local(
    surface: str, api_token: Optional[str], store: MemoryStore,
) -> bool:
    if surface in LOCAL_SURFACES:
        return True
    if api_token and hasattr(store, "get_principal"):
        for pid in ("principal_local_cli", "principal_local_api"):
            p = store.get_principal(pid)
            if p and (p.metadata or {}).get("api_token") == api_token:
                return True
    return False


def principal_has_capability(
    principal: Principal,
    capability: str,
    *,
    domain: Optional[str] = None,
    vault_id: Optional[str] = None,
    project_id: Optional[str] = None,
) -> bool:
    caps = set(principal.capabilities or [])
    if "*" in caps or "privacy:admin" in caps:
        return True
    if capability in caps:
        return True
    # Scoped forms
    candidates = [capability]
    if domain:
        candidates.append(f"read:domain:{domain}")
    if vault_id:
        candidates.append(f"read:vault:{vault_id.replace('vault_', '')}")
        candidates.append(f"read:vault:{vault_id}")
    if project_id:
        candidates.append(f"read:project:{project_id}")
    return any(c in caps for c in candidates)


def validate_vault_access(
    store: MemoryStore,
    *,
    vault_id: str,
    persona: str,
    principal: Optional[Principal] = None,
    allowed_vaults_extra: Optional[list[str]] = None,
) -> bool:
    """Deny unknown vaults. No wildcard personas in defaults."""
    if allowed_vaults_extra and (
        vault_id in allowed_vaults_extra or "*" in allowed_vaults_extra
    ):
        pass  # principal/binding may expand; still check persona on vault
    if principal and principal.allowed_vaults:
        if vault_id not in principal.allowed_vaults and "*" not in principal.allowed_vaults:
            return False

    vault: Optional[Vault] = None
    if hasattr(store, "get_vault"):
        vault = store.get_vault(vault_id)
    if vault is not None:
        allowed = set(vault.allowed_personas or [])
        return persona in allowed

    # Unknown vault id → default-deny (except known defaults without *)
    allowed = DEFAULT_VAULT_PERSONAS.get(vault_id)
    if allowed is None:
        return False
    return persona in allowed


def active_consent_covers(
    store: MemoryStore,
    *,
    subject_ids: list[str],
    purpose: str,
    tool_id: str,
    categories: list[str],
    execution_location: str = "unknown",
) -> bool:
    if not subject_ids:
        return True
    if not hasattr(store, "list_consents"):
        return False
    from .models import ConsentStatus
    required = set(categories or [])
    for c in store.list_consents(status=ConsentStatus.active.value):
        if c.subject_id not in subject_ids and c.subject_id != "*":
            continue
        if c.purposes and purpose not in c.purposes and "*" not in c.purposes:
            continue
        if c.allowed_tools:
            tools = set(c.allowed_tools)
            if "*" in tools:
                pass
            elif tool_id in tools:
                pass
            elif "local" in tools and execution_location == "local":
                pass
            elif "cloud" in tools and execution_location == "cloud":
                pass
            else:
                continue
        if c.data_categories and required:
            allowed_cats = set(c.data_categories)
            if "*" not in allowed_cats and not required.issubset(allowed_cats):
                continue
        if c.valid_until and c.valid_until < now_iso():
            continue
        return True
    return False


def ensure_local_identity(store: MemoryStore) -> Principal:
    """Admin/bootstrap helper — create local CLI principal + vaults if missing."""
    for vid, personas in DEFAULT_VAULT_PERSONAS.items():
        if hasattr(store, "get_vault") and store.get_vault(vid) is None:
            store.insert_vault(Vault(
                id=vid,
                name=vid,
                allowed_personas=sorted(personas),
            ))
    existing = store.get_principal("principal_local_cli") if hasattr(store, "get_principal") else None
    if existing:
        return existing
    p = Principal(
        id="principal_local_cli",
        type=PrincipalType.user,
        name="Local CLI",
        trusted=True,
        local=True,
        capabilities=[
            "read_context_pack",
            "read:domain:technical",
            "read:domain:work",
            "read:domain:finance",
            "read:vault:vault_general",
            "read:vault:vault_work",
            "read:vault:vault_personal",
            "read:vault:vault_restricted",
            "session:write",
            "privacy:admin",
        ],
        allowed_personas=["individual", "developer", "employee", "assistant_user"],
        allowed_purposes=["*", "memory_retrieval", "task_execution", "financial_planning",
                          "personal_planning", "debugging"],
        allowed_audiences=["self", "local"],
        allowed_vaults=list(DEFAULT_VAULT_PERSONAS.keys()),
    )
    store.insert_principal(p)
    # Local binding for tool local-cli (no credential — surface auth is enough)
    if hasattr(store, "get_client_binding_by_client"):
        if store.get_client_binding_by_client("local-cli") is None:
            register_client_binding(
                store,
                client_id="local-cli",
                tool_id="local-cli",
                principal_id=p.id,
                capabilities=list(p.capabilities),
                allowed_personas=list(p.allowed_personas),
                allowed_purposes=list(p.allowed_purposes),
                allowed_audiences=list(p.allowed_audiences),
                allowed_vaults=list(p.allowed_vaults),
            )
    return p
