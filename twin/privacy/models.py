"""v0.5 privacy & governance models.

Judgment explains how the user thinks. Governance decides what the system
may expose. The main LLM never interprets prose to authorize access.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class PrincipalType(str, Enum):
    user = "user"
    tool = "tool"
    connector = "connector"
    service = "service"
    agent = "agent"


class PolicyEffect(str, Enum):
    allow = "allow"
    deny = "deny"
    redact = "redact"
    aggregate = "aggregate"
    generalize = "generalize"
    pseudonymize = "pseudonymize"
    require_grant = "require_grant"
    require_confirmation = "require_confirmation"
    quarantine = "quarantine"


class GrantStatus(str, Enum):
    active = "active"
    exhausted = "exhausted"
    expired = "expired"
    revoked = "revoked"


class ConsentStatus(str, Enum):
    active = "active"
    withdrawn = "withdrawn"
    expired = "expired"
    unknown = "unknown"


class QuarantineStatus(str, Enum):
    quarantined = "quarantined"
    released = "released"
    released_sanitized = "released_sanitized"
    rejected = "rejected"


class DeletionMode(str, Enum):
    delete = "delete"
    anonymize = "anonymize"
    detach = "detach"
    crypto_shred = "crypto_shred"


class DeletionStatus(str, Enum):
    preview = "preview"
    approved = "approved"
    running = "running"
    completed = "completed"
    completed_with_residuals = "completed_with_residuals"
    failed = "failed"
    invalidated = "invalidated"


class SensitivityClass(str, Enum):
    public = "public"
    internal = "internal"
    confidential = "confidential"
    restricted = "restricted"
    highly_restricted = "highly_restricted"


PRIVACY_LABELS = frozenset({
    "pii", "financial", "health", "employment_confidential", "authentication",
    "legal", "relationship", "location", "third_party", "minor", "credential",
    "secret", "biometric",
})


class Principal(BaseModel):
    id: str
    type: PrincipalType = PrincipalType.tool
    name: str = ""
    trusted: bool = False
    local: bool = True
    capabilities: list[str] = Field(default_factory=list)
    allowed_personas: list[str] = Field(default_factory=list)
    allowed_purposes: list[str] = Field(default_factory=list)
    allowed_audiences: list[str] = Field(default_factory=list)
    allowed_vaults: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class ClientBinding(BaseModel):
    """Authenticated client registration — not a self-asserted tool name."""
    id: str
    client_id: str
    tool_id: str
    principal_id: str
    credential_hash: Optional[str] = None
    capabilities: list[str] = Field(default_factory=list)
    allowed_personas: list[str] = Field(default_factory=list)
    allowed_purposes: list[str] = Field(default_factory=list)
    allowed_audiences: list[str] = Field(default_factory=list)
    allowed_vaults: list[str] = Field(default_factory=list)
    revoked_at: Optional[str] = None
    created_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolIdentity(BaseModel):
    id: str
    execution_location: str = "local"  # local | cloud | unknown
    provider: str = ""
    data_retention: str = "unknown"
    supports_redaction: bool = True
    trusted_level: str = "external"  # local | trusted | external
    allowed_data_classes: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PersonaRecord(BaseModel):
    """Operational persona — scope authority, not just a label.

    Capabilities listed here further *restrict* principal∩binding; they never
    amplify. Empty domains/vault_ids means inherit (no extra restriction).
    """

    id: str
    name: str = ""
    domains: list[str] = Field(default_factory=list)
    vault_ids: list[str] = Field(default_factory=list)
    capabilities: list[str] = Field(default_factory=list)
    default_policies: list[str] = Field(default_factory=list)
    active: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class Vault(BaseModel):
    id: str
    name: str = ""
    encryption_key_id: Optional[str] = None
    storage_backend: str = "logical"
    physical_boundary: str = "logical"
    allowed_personas: list[str] = Field(default_factory=list)
    # v0.6: per-organization separation (design allows future physical split)
    storage_namespace: Optional[str] = None
    backup_class: str = "personal"
    source_owner: Optional[str] = None


class AccessRequest(BaseModel):
    """Common authorization context for every sensitive call.

    Defaults are restricted/unknown — never privileged local-cli.
    Server surfaces must resolve identity via ``resolve_access``.
    """
    principal_id: str = "unknown"
    persona: str = "unknown"
    purpose: str = "unknown"
    audience: str = "unknown"
    tool_id: str = "unknown"
    project_id: Optional[str] = None
    session_id: Optional[str] = None
    requested_domains: list[str] = Field(default_factory=list)
    requested_actions: list[str] = Field(default_factory=lambda: ["read"])
    resource_ids: list[str] = Field(default_factory=list)
    execution_location: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @property
    def is_restricted_mode(self) -> bool:
        return (
            self.purpose in ("", "unknown")
            or self.audience in ("", "unknown")
            or self.tool_id in ("", "unknown")
            or self.persona in ("", "unknown")
            or self.principal_id in ("", "unknown")
        )


class PolicySubjects(BaseModel):
    personas: list[str] = Field(default_factory=lambda: ["*"])
    principals: list[str] = Field(default_factory=lambda: ["*"])


class PolicyResources(BaseModel):
    domains: list[str] = Field(default_factory=list)
    sensitivity: list[str] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)
    source_owners: list[str] = Field(default_factory=list)
    vaults: list[str] = Field(default_factory=list)
    third_party: Optional[bool] = None


class PolicyContext(BaseModel):
    purposes: list[str] = Field(default_factory=lambda: ["*"])
    audiences: list[str] = Field(default_factory=lambda: ["*"])
    tools: list[str] = Field(default_factory=lambda: ["*"])
    execution_locations: list[str] = Field(default_factory=list)


class PrivacyPolicy(BaseModel):
    id: str
    name: str = ""
    effect: PolicyEffect = PolicyEffect.deny
    priority: int = 100
    enabled: bool = True
    overrideable: bool = True
    constitutional: bool = False
    subjects: PolicySubjects = Field(default_factory=PolicySubjects)
    resources: PolicyResources = Field(default_factory=PolicyResources)
    context: PolicyContext = Field(default_factory=PolicyContext)
    obligations: list[str] = Field(default_factory=list)
    reason: str = ""
    created_at: str = ""
    version: int = 1
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolicySetVersion(BaseModel):
    id: str
    version: int
    created_at: str
    reason: str = ""
    policy_ids: list[str] = Field(default_factory=list)
    revision_ids: list[str] = Field(default_factory=list)
    active: bool = True
    actor: str = "user"
    metadata: dict[str, Any] = Field(default_factory=dict)


class PrivacyPolicyRevision(BaseModel):
    """Immutable policy payload at evaluation time (v0.4-style)."""
    id: str
    policy_id: str
    version: int = 1
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    actor: str = "system"
    reason: str = ""


class ResourceDecision(BaseModel):
    resource_id: str
    effect: PolicyEffect
    matched_policy_ids: list[str] = Field(default_factory=list)
    redacted_fields: list[str] = Field(default_factory=list)
    redaction_plan_id: Optional[str] = None
    reason: str = ""
    grant_id: Optional[str] = None
    labels: list[str] = Field(default_factory=list)
    sensitivity: Optional[str] = None
    obligations: list[str] = Field(default_factory=list)


class PrivacyDecision(BaseModel):
    id: str
    request_fingerprint: str = ""
    effect: PolicyEffect = PolicyEffect.allow
    matched_policy_ids: list[str] = Field(default_factory=list)
    policy_revision_ids: list[str] = Field(default_factory=list)
    resource_decisions: list[ResourceDecision] = Field(default_factory=list)
    obligations: list[str] = Field(default_factory=list)
    policy_set_version_id: Optional[str] = None
    grant_ids: list[str] = Field(default_factory=list)
    access_request: dict[str, Any] = Field(default_factory=dict)
    engine_version: str = "privacy-engine-v1"
    created_at: str = ""
    expires_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PermissionGrant(BaseModel):
    id: str
    principal_id: str
    granted_by: str = "user"
    persona: str = "individual"
    purpose: str = ""
    tool_ids: list[str] = Field(default_factory=list)
    audiences: list[str] = Field(default_factory=list)
    execution_locations: list[str] = Field(default_factory=list)
    requested_actions: list[str] = Field(default_factory=lambda: ["read"])
    session_id: Optional[str] = None
    resource_scope: dict[str, Any] = Field(default_factory=dict)
    allowed_effects: list[str] = Field(default_factory=lambda: ["read_redacted"])
    valid_from: str = ""
    valid_until: Optional[str] = None
    max_uses: Optional[int] = 1
    uses: int = 0
    version: int = 1
    revoked_at: Optional[str] = None
    reason: str = ""
    status: GrantStatus = GrantStatus.active
    metadata: dict[str, Any] = Field(default_factory=dict)


class ConsentRecord(BaseModel):
    id: str
    subject_id: str
    granted_by: str = ""
    recorded_by: str = "user"
    purposes: list[str] = Field(default_factory=list)
    data_categories: list[str] = Field(default_factory=list)
    allowed_tools: list[str] = Field(default_factory=lambda: ["local"])
    valid_until: Optional[str] = None
    evidence_artifact_id: Optional[str] = None
    status: ConsentStatus = ConsentStatus.active
    created_at: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class RedactionOp(BaseModel):
    path: str
    action: str  # remove | generalize | pseudonymize | mask
    value: Optional[str] = None


class RedactionPlan(BaseModel):
    id: str
    resource_id: str
    operations: list[RedactionOp] = Field(default_factory=list)
    policy_ids: list[str] = Field(default_factory=list)
    created_at: str = ""


class QuarantineRecord(BaseModel):
    id: str
    artifact_id: Optional[str] = None
    percept_id: Optional[str] = None
    reason: str = ""
    detected_patterns: list[str] = Field(default_factory=list)
    severity: str = "high"
    status: QuarantineStatus = QuarantineStatus.quarantined
    content_fingerprint: str = ""
    created_at: str = ""
    resolved_at: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class LeakageCanary(BaseModel):
    id: str
    token: str
    vault_id: str = "vault_general"
    placed_in: list[str] = Field(default_factory=list)
    created_at: str = ""
    active: bool = True


class ExportRecord(BaseModel):
    id: str
    requested_by: str = "user"
    purpose: str = "backup"
    destination: str = "local_encrypted_file"
    resource_scope: dict[str, Any] = Field(default_factory=dict)
    policy_decision_id: Optional[str] = None
    redaction_plan_id: Optional[str] = None
    vaults: list[str] = Field(default_factory=list)
    manifest: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    expires_at: Optional[str] = None
    revoked_at: Optional[str] = None


class DeletionRequest(BaseModel):
    id: str
    selector: dict[str, Any] = Field(default_factory=dict)
    mode: DeletionMode = DeletionMode.delete
    requested_by: str = "user"
    reason: str = ""
    status: DeletionStatus = DeletionStatus.preview
    preview: dict[str, Any] = Field(default_factory=dict)
    # Immutable execution plan (full ID set) — never truncated
    manifest: dict[str, Any] = Field(default_factory=dict)
    preview_token: str = ""
    created_at: str = ""
    completed_at: Optional[str] = None


class FieldSensitivity(BaseModel):
    sensitivity: SensitivityClass = SensitivityClass.internal
    labels: list[str] = Field(default_factory=list)
    third_party: bool = False
    owner: Optional[str] = None


class ResourceClassification(BaseModel):
    """Derived classification for a memory/resource under evaluation."""
    resource_id: str
    domain: str = "general"
    sensitivity: str = "internal"
    labels: list[str] = Field(default_factory=list)
    persona: str = "individual"
    vault_id: str = "vault_general"
    source_owner: str = "user"
    subjects: list[str] = Field(default_factory=list)
    third_party: bool = False
    fields: dict[str, FieldSensitivity] = Field(default_factory=dict)
    payload: dict[str, Any] = Field(default_factory=dict)
    title: str = ""
    summary: str = ""
