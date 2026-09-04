"""Trusted access context — server resolves identity; clients never self-assert.

Effective authority is always an intersection:

    authenticated principal
  ∩ client binding
  ∩ persona allowance
  ∩ scoped capability
  ∩ vault allowance
  ∩ policy
  ∩ grant

Binding never amplifies principal. External surfaces require a credential.
"""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from .. import ids
from ..clock import now_iso
from twin.store.store.base import TwinStore
from .models import (
    AccessRequest,
    ClientBinding,
    PersonaRecord,
    Principal,
    PrincipalType,
    ToolIdentity,
    Vault,
)
from .yaml_io import resolve_tool

# Default purpose for packs / retrieval.
DEFAULT_PURPOSE = "context_retrieval"


def normalize_purpose(purpose: str) -> str:
    return purpose


def purpose_allowed(purpose: str, allowed: list[str] | tuple[str, ...] | set[str]) -> bool:
    """True when ``purpose`` is covered by ``allowed`` (or ``*``)."""
    if not allowed:
        return True
    if "*" in allowed:
        return True
    return purpose in allowed


LOCAL_SURFACES = frozenset({"cli", "local-cli", "twin-cli"})
NATIVE_SURFACES = frozenset({"native"})
EXTERNAL_SURFACES = frozenset({"mcp", "http", "api", "unknown", ""})
# Allowlist tool for native local hooks — never the host product name.
NATIVE_HOST_TOOL_ID = "native-host"

# No wildcards — unknown persona on a vault is deny.
DEFAULT_VAULT_PERSONAS: dict[str, set[str]] = {
    "vault_general": {"individual", "developer", "employee", "assistant_user",
                      "tech_lead", "personal_project_builder"},
    "vault_work": {"employee", "developer", "tech_lead"},
    "vault_personal": {"individual", "assistant_user", "private_individual",
                       "personal_project_builder"},
    "vault_restricted": {"individual", "private_individual"},
}


def default_persona_records() -> list[PersonaRecord]:
    """Configurable starter personas — scope authority, not labels."""
    return [
        PersonaRecord(
            id="global", name="Global",
            domains=["*"], vault_ids=["vault_general"],
        ),
        PersonaRecord(
            id="individual", name="Individual",
            domains=["technical", "personal_preferences", "assistant_preferences"],
            vault_ids=["vault_general", "vault_personal"],
        ),
        PersonaRecord(
            id="developer", name="Developer",
            domains=["technical", "work"],
            vault_ids=["vault_general", "vault_work"],
        ),
        PersonaRecord(
            id="tech_lead", name="Tech lead",
            domains=["technical", "work"],
            vault_ids=["vault_general", "vault_work"],
        ),
        PersonaRecord(
            id="employee", name="Employee",
            domains=["work", "technical"],
            vault_ids=["vault_work", "vault_general"],
        ),
        PersonaRecord(
            id="personal_project_builder", name="Personal-project builder",
            domains=["technical", "personal_preferences"],
            vault_ids=["vault_general", "vault_personal"],
        ),
        PersonaRecord(
            id="private_individual", name="Private individual",
            domains=["personal_preferences"],
            vault_ids=["vault_personal", "vault_restricted"],
            capabilities=["read_context_pack", "read:vault:vault_personal",
                          "read:vault:vault_restricted",
                          "read:domain:personal_preferences"],
        ),
        PersonaRecord(
            id="assistant_user", name="Assistant user",
            domains=["assistant_preferences", "technical"],
            vault_ids=["vault_general", "vault_personal"],
        ),
    ]


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
    store: Optional[TwinStore] = None,
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


def intersect_allowlists(
    base: Optional[list[str]],
    restrictor: Optional[list[str]],
) -> list[str]:
    """Binding never amplifies — only restricts (or inherits when empty)."""
    base_s = set(base or [])
    if not restrictor:
        return sorted(base_s)
    rest_s = set(restrictor)
    if "*" in base_s:
        return ["*"] if "*" in rest_s else sorted(rest_s)
    if "*" in rest_s:
        return sorted(base_s)
    return sorted(base_s & rest_s)


def intersect_capabilities(
    principal_caps: Optional[list[str]],
    binding_caps: Optional[list[str]],
) -> list[str]:
    return intersect_allowlists(principal_caps, binding_caps)


def register_client_binding(
    store: TwinStore,
    *,
    client_id: str,
    tool_id: str,
    principal_id: str,
    credential: Optional[str] = None,
    authentication_mode: str = "credential",
    capabilities: Optional[list[str]] = None,
    allowed_personas: Optional[list[str]] = None,
    allowed_purposes: Optional[list[str]] = None,
    allowed_audiences: Optional[list[str]] = None,
    allowed_vaults: Optional[list[str]] = None,
) -> ClientBinding:
    """Administrative provisioning — never called from a read path.

    External MCP/HTTP clients must receive a credential (or an explicit
    trusted_local_transport mode that the surface can prove).
    """
    if authentication_mode not in ("credential", "trusted_local_transport"):
        raise ValueError("authentication_mode must be credential | trusted_local_transport")
    if authentication_mode == "credential" and not credential:
        raise ValueError("credential required for authentication_mode=credential")
    binding = ClientBinding(
        id=ids.new_id("cbind"),
        client_id=client_id,
        tool_id=tool_id,
        principal_id=principal_id,
        credential_hash=hash_credential(credential) if credential else None,
        capabilities=list(capabilities or []),
        allowed_personas=list(allowed_personas or ["individual"]),
        allowed_purposes=list(allowed_purposes or ["context_retrieval", "task_execution", "*"]),
        allowed_audiences=list(allowed_audiences or ["self"]),
        allowed_vaults=list(allowed_vaults or ["vault_general"]),
        created_at=now_iso(),
        metadata={"authentication_mode": authentication_mode},
    )
    store.insert_client_binding(binding)
    return binding


def resolve_access(
    store: TwinStore,
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
    trusted_local_transport: bool = False,
) -> AccessRequest:
    """Build a trusted AccessRequest from authenticated binding or local CLI."""
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

    # Authenticated local CLI — or native local-hook transport. Native uses the
    # same local principal bootstrap but records surface=native + host client;
    # tool allowlists use ``native-host``, never the host product name as tool_id.
    if (
        surface_l in LOCAL_SURFACES
        or surface_l in NATIVE_SURFACES
        or _authenticated_local(surface_l, api_token, store)
    ):
        principal = None
        if hasattr(store, "get_principal"):
            principal = store.get_principal(principal_id or "principal_local_cli")
        if principal is None:
            return restricted_access(
                project_id=project_id, session_id=session_id,
                requested_domains=requested_domains, claims=claims,
            )
        if surface_l in NATIVE_SURFACES:
            resolved_tool = NATIVE_HOST_TOOL_ID
            extra_meta = {
                "surface": "native",
                "client": client_l or "",
                "trusted_level": "local",
            }
        else:
            resolved_tool = "local-cli"
            extra_meta = {"surface": "cli", "trusted_level": "local"}
        return _apply_allowlists(
            store=store,
            principal=principal,
            tool_id=resolved_tool,
            persona=persona,
            purpose=purpose,
            audience=audience,
            project_id=project_id,
            session_id=session_id,
            requested_domains=requested_domains,
            claims=claims,
            binding=None,
            extra_meta=extra_meta,
        )

    # External / MCP / HTTP — require registered + authenticated binding
    binding = _find_binding(
        store, client_l or tool_id, api_token,
        surface=surface_l,
        trusted_local_transport=trusted_local_transport,
    )
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
        store=store,
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
    store: TwinStore,
    client_key: Optional[str],
    api_token: Optional[str],
    *,
    surface: str,
    trusted_local_transport: bool = False,
) -> Optional[ClientBinding]:
    if not client_key or not hasattr(store, "get_client_binding_by_client"):
        return None
    binding = store.get_client_binding_by_client(client_key)
    if binding is None or binding.revoked_at:
        return None

    auth_mode = (binding.metadata or {}).get("authentication_mode") or (
        "credential" if binding.credential_hash else "none"
    )

    # External surfaces: name alone never authenticates
    if surface in EXTERNAL_SURFACES or surface not in LOCAL_SURFACES:
        if auth_mode == "trusted_local_transport":
            if not trusted_local_transport:
                return None
        elif not binding.credential_hash:
            return None
        else:
            if not api_token or hash_credential(api_token) != binding.credential_hash:
                return None
    elif binding.credential_hash:
        if not api_token or hash_credential(api_token) != binding.credential_hash:
            return None
    return binding


def _apply_allowlists(
    *,
    store: TwinStore,
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
    # Binding ∩ principal — binding never amplifies
    allowed_personas = intersect_allowlists(
        principal.allowed_personas or (["individual"] if principal.local else []),
        binding.allowed_personas if binding else None,
    )
    allowed_purposes = intersect_allowlists(
        principal.allowed_purposes or ["context_retrieval", "task_execution"],
        binding.allowed_purposes if binding else None,
    )
    allowed_audiences = intersect_allowlists(
        principal.allowed_audiences or ["self"],
        binding.allowed_audiences if binding else None,
    )
    allowed_vaults = intersect_allowlists(
        principal.allowed_vaults,
        binding.allowed_vaults if binding else None,
    )
    caps = intersect_capabilities(
        principal.capabilities,
        binding.capabilities if binding else None,
    )

    # Prefer individual when the caller did not name a persona. sorted()
    # intersection would otherwise default to "developer" and strip personal
    # vaults via PersonaRecord — surprising for connector/MCP tools.
    if persona:
        requested_persona = persona
    elif not allowed_personas:
        requested_persona = "unknown"
    elif "individual" in allowed_personas or "*" in allowed_personas:
        requested_persona = "individual"
    else:
        requested_persona = allowed_personas[0]
    requested_purpose = normalize_purpose(purpose or DEFAULT_PURPOSE)
    requested_audience = audience or "self"

    if allowed_personas and requested_persona not in allowed_personas and "*" not in allowed_personas:
        return restricted_access(
            project_id=project_id, session_id=session_id,
            requested_domains=requested_domains, claims=claims,
        )
    if allowed_purposes and not purpose_allowed(requested_purpose, allowed_purposes):
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

    # PersonaRecord further restricts — never amplifies principal∩binding.
    persona_rec = None
    if hasattr(store, "get_persona"):
        persona_rec = store.get_persona(requested_persona)
    domains_out = list(requested_domains or [])
    if persona_rec is not None and persona_rec.active:
        if persona_rec.vault_ids:
            allowed_vaults = intersect_allowlists(allowed_vaults, persona_rec.vault_ids)
        if persona_rec.capabilities:
            caps = intersect_capabilities(caps, persona_rec.capabilities)
        if persona_rec.domains and "*" not in persona_rec.domains:
            if domains_out:
                domains_out = intersect_allowlists(domains_out, persona_rec.domains)
            else:
                # No explicit request: inherit persona domains (still ≤ persona).
                domains_out = list(persona_rec.domains)
            # Empty intersection → fail closed (restricted)
            if not domains_out:
                return restricted_access(
                    project_id=project_id, session_id=session_id,
                    requested_domains=requested_domains, claims={
                        **claims, "reason": "persona_domain_intersection_empty",
                    },
                )

    return AccessRequest(
        principal_id=principal.id,
        persona=requested_persona,
        purpose=requested_purpose,
        audience=requested_audience,
        tool_id=tool_id,
        project_id=project_id,
        session_id=session_id,
        requested_domains=domains_out,
        execution_location=None,
        metadata={
            **extra_meta,
            "claims": claims,
            "resolved_capabilities": caps,
            "allowed_personas": allowed_personas,
            "allowed_vaults": allowed_vaults,
            "persona_id": persona_rec.id if persona_rec else requested_persona,
            "persona_domains": list(persona_rec.domains) if persona_rec else [],
            "persona_vault_ids": list(persona_rec.vault_ids) if persona_rec else [],
        },
    )


def _authenticated_local(
    surface: str, api_token: Optional[str], store: TwinStore,
) -> bool:
    if surface in LOCAL_SURFACES:
        return True
    if api_token and hasattr(store, "get_principal"):
        for pid in ("principal_local_cli", "principal_local_api"):
            p = store.get_principal(pid)
            if p and (p.metadata or {}).get("api_token") == api_token:
                return True
    return False


def _scope_matches(caps: set[str], prefix: str, value: Optional[str]) -> bool:
    """If any prefix scopes exist, value must match one (or wildcard).

    Declared scopes never widen when the required context value is omitted.
    """
    scoped = {c for c in caps if c.startswith(prefix + ":")}
    if not scoped:
        return True  # no scopes of this kind → not restricting
    if value is None:
        return False
    return f"{prefix}:{value}" in scoped or f"{prefix}:*" in scoped


def principal_can_read(
    principal: Principal,
    *,
    domain: Optional[str] = None,
    vault_id: Optional[str] = None,
    project_id: Optional[str] = None,
    effective_capabilities: Optional[list[str]] = None,
) -> bool:
    """Base action AND resource scopes (never base OR scope)."""
    caps = set(
        effective_capabilities
        if effective_capabilities is not None
        else (principal.capabilities or [])
    )
    if "*" in caps or "privacy:admin" in caps:
        return True
    if "read_context_pack" not in caps:
        return False
    if not _scope_matches(caps, "read:domain", domain):
        return False
    scoped_vaults = {c for c in caps if c.startswith("read:vault:")}
    if scoped_vaults:
        if not vault_id:
            return False
        short = vault_id.replace("vault_", "") if vault_id.startswith("vault_") else vault_id
        ok = (
            f"read:vault:{vault_id}" in scoped_vaults
            or f"read:vault:{short}" in scoped_vaults
            or "read:vault:*" in scoped_vaults
        )
        if not ok:
            return False
    if not _scope_matches(caps, "read:project", project_id):
        return False
    return True


def principal_has_capability(
    principal: Principal,
    capability: str,
    *,
    domain: Optional[str] = None,
    vault_id: Optional[str] = None,
    project_id: Optional[str] = None,
    effective_capabilities: Optional[list[str]] = None,
) -> bool:
    """Backward-compatible entry; read paths use principal_can_read semantics."""
    if capability == "read_context_pack":
        return principal_can_read(
            principal,
            domain=domain,
            vault_id=vault_id,
            project_id=project_id,
            effective_capabilities=effective_capabilities,
        )
    caps = set(
        effective_capabilities
        if effective_capabilities is not None
        else (principal.capabilities or [])
    )
    if "*" in caps or "privacy:admin" in caps:
        return True
    return capability in caps


def validate_vault_access(
    store: TwinStore,
    *,
    vault_id: str,
    persona: str,
    principal: Optional[Principal] = None,
    allowed_vaults_extra: Optional[list[str]] = None,
) -> bool:
    """Effective vaults = principal ∩ binding; then persona must be allowed."""
    principal_vaults = list((principal.allowed_vaults if principal else None) or [])
    effective = intersect_allowlists(principal_vaults, allowed_vaults_extra)
    # If either side declared vaults, enforce membership
    if principal_vaults or allowed_vaults_extra:
        if "*" not in effective and vault_id not in effective:
            return False

    vault: Optional[Vault] = None
    if hasattr(store, "get_vault"):
        vault = store.get_vault(vault_id)
    if vault is not None:
        return persona in set(vault.allowed_personas or [])

    allowed = DEFAULT_VAULT_PERSONAS.get(vault_id)
    if allowed is None:
        return False
    return persona in allowed


def active_consent_covers(
    store: TwinStore,
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
        if c.purposes and not purpose_allowed(purpose, c.purposes):
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


def ensure_local_identity(store: TwinStore) -> Principal:
    """Admin/bootstrap helper — create local CLI principal + vaults if missing."""
    from twin.privacy.vault import vault_display_name

    for vid, personas in DEFAULT_VAULT_PERSONAS.items():
        if not hasattr(store, "get_vault"):
            continue
        label = vault_display_name(vid)
        existing = store.get_vault(vid)
        if existing is None:
            store.insert_vault(Vault(
                id=vid,
                name=label,
                allowed_personas=sorted(personas),
            ))
        elif hasattr(store, "update_vault") and (
            not (existing.name or "").strip() or existing.name == vid
        ):
            store.update_vault(vid, name=label, allowed_personas=sorted(personas))
    if hasattr(store, "get_persona") and hasattr(store, "insert_persona"):
        for rec in default_persona_records():
            if store.get_persona(rec.id) is None:
                store.insert_persona(rec)
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
            "read:domain:personal_preferences",
            "read:domain:assistant_preferences",
            "read:vault:vault_general",
            "read:vault:vault_work",
            "read:vault:vault_personal",
            "read:vault:vault_restricted",
            "session:write",
            "privacy:admin",
        ],
        allowed_personas=[
            "individual", "developer", "employee", "assistant_user",
            "tech_lead", "personal_project_builder", "private_individual", "global",
        ],
        allowed_purposes=["*", "context_retrieval", "task_execution", "financial_planning",
                          "personal_planning", "debugging"],
        allowed_audiences=["self", "local"],
        allowed_vaults=list(DEFAULT_VAULT_PERSONAS.keys()),
    )
    store.insert_principal(p)
    # Local binding is surface-authenticated (CLI path), not name-authenticated
    if hasattr(store, "get_client_binding_by_client"):
        if store.get_client_binding_by_client("local-cli") is None:
            binding = ClientBinding(
                id=ids.new_id("cbind"),
                client_id="local-cli",
                tool_id="local-cli",
                principal_id=p.id,
                credential_hash=None,
                capabilities=list(p.capabilities),
                allowed_personas=list(p.allowed_personas),
                allowed_purposes=list(p.allowed_purposes),
                allowed_audiences=list(p.allowed_audiences),
                allowed_vaults=list(p.allowed_vaults),
                created_at=now_iso(),
                metadata={"authentication_mode": "trusted_local_transport"},
            )
            store.insert_client_binding(binding)
    return p
