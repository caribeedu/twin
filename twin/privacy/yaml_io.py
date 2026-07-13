"""Governance policy YAML bootstrap/export + tool/persona registry defaults."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

import yaml

from .. import ids
from ..clock import now_iso
from ..memory.store.base import MemoryStore
from .models import (
    PolicyContext,
    PolicyEffect,
    PolicyResources,
    PolicySetVersion,
    PolicySubjects,
    PrivacyPolicy,
    ToolIdentity,
)

DEFAULT_TOOLS: dict[str, ToolIdentity] = {
    "local-cli": ToolIdentity(id="local-cli", execution_location="local", trusted_level="local"),
    "local-ollama": ToolIdentity(id="local-ollama", execution_location="local", trusted_level="local"),
    "cursor": ToolIdentity(id="cursor", execution_location="local", provider="Cursor", trusted_level="trusted"),
    "claude-desktop": ToolIdentity(
        id="claude-desktop", execution_location="cloud", provider="Anthropic", trusted_level="external",
    ),
    "chatgpt-cloud": ToolIdentity(
        id="chatgpt-cloud", execution_location="cloud", provider="OpenAI", trusted_level="external",
    ),
    "public-export": ToolIdentity(
        id="public-export", execution_location="cloud", trusted_level="external",
    ),
}


def builtin_governance_policies() -> list[PrivacyPolicy]:
    now = now_iso()
    return [
        PrivacyPolicy(
            id="pol_no_work_to_personal_cloud",
            name="No employer data to personal cloud tools",
            effect=PolicyEffect.deny,
            priority=900,
            constitutional=True,
            overrideable=False,
            subjects=PolicySubjects(personas=["individual", "assistant_user"]),
            resources=PolicyResources(source_owners=["employer"], domains=["work"]),
            context=PolicyContext(execution_locations=["cloud"], tools=["*"]),
            reason="Employer-owned work data must not reach personal cloud tools",
            created_at=now,
            obligations=["log_decision"],
        ),
        PrivacyPolicy(
            id="pol_no_credentials_anywhere",
            name="Credentials never leave the vault",
            effect=PolicyEffect.deny,
            priority=1000,
            constitutional=True,
            overrideable=False,
            resources=PolicyResources(labels=["credential", "authentication", "secret"]),
            context=PolicyContext(tools=["*"], purposes=["*"], audiences=["*"]),
            reason="Credentials and secrets are never injectable",
            created_at=now,
        ),
        PrivacyPolicy(
            id="pol_third_party_no_public",
            name="Third-party confidential data not for public output",
            effect=PolicyEffect.deny,
            priority=850,
            resources=PolicyResources(third_party=True),
            context=PolicyContext(audiences=["public", "client", "unknown"]),
            reason="Third-party data requires consent before external disclosure",
            created_at=now,
        ),
        PrivacyPolicy(
            id="pol_finance_cloud_redact",
            name="Generalize finance for cloud tools",
            effect=PolicyEffect.generalize,
            priority=700,
            resources=PolicyResources(domains=["finance"], labels=["financial"]),
            context=PolicyContext(execution_locations=["cloud"]),
            reason="Exact financial figures require grant or generalization for cloud",
            created_at=now,
            obligations=["log_decision", "do_not_cache"],
        ),
        PrivacyPolicy(
            id="pol_restricted_require_grant_cloud",
            name="Restricted data to cloud requires grant",
            effect=PolicyEffect.require_grant,
            priority=800,
            resources=PolicyResources(sensitivity=["restricted", "highly_restricted"]),
            context=PolicyContext(execution_locations=["cloud"]),
            reason="Restricted personal data needs an explicit temporary grant for cloud tools",
            created_at=now,
        ),
        PrivacyPolicy(
            id="pol_relationship_no_work_persona",
            name="Relationship data blocked for employee persona",
            effect=PolicyEffect.deny,
            priority=820,
            subjects=PolicySubjects(personas=["employee", "developer"]),
            resources=PolicyResources(domains=["relationship", "family", "health", "emotional"]),
            reason="Intimate domains do not flow into work personas",
            created_at=now,
        ),
    ]


def load_governance_policies(
    path: Optional[Path | str] = None,
    *,
    store: Optional[MemoryStore] = None,
) -> list[PrivacyPolicy]:
    policies = {p.id: p for p in builtin_governance_policies()}
    if path and Path(path).exists():
        data = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        for raw in data.get("governance") or data.get("privacy_policies") or []:
            p = _policy_from_yaml(raw)
            policies[p.id] = p
    if store is not None and hasattr(store, "list_privacy_policies"):
        for p in store.list_privacy_policies(enabled=True):
            policies[p.id] = p
    return list(policies.values())


def _policy_from_yaml(raw: dict[str, Any]) -> PrivacyPolicy:
    when = raw.get("when") or raw.get("if") or {}
    subjects = raw.get("subjects") or {}
    resources = raw.get("resources") or {}
    context = raw.get("context") or {}
    # compact when: form
    if when:
        subjects = {
            "personas": when.get("persona", when.get("personas", ["*"])),
            "principals": when.get("principals", ["*"]),
        }
        if isinstance(subjects["personas"], str):
            subjects["personas"] = [subjects["personas"]]
        resources = {
            "domains": when.get("domains", []),
            "sensitivity": when.get("sensitivity", []),
            "labels": when.get("labels", []),
            "source_owners": (
                [when["resource.source_owner"]]
                if "resource.source_owner" in when else when.get("source_owners", [])
            ),
            "third_party": when.get("third_party"),
        }
        context = {
            "purposes": when.get("purposes", ["*"]),
            "audiences": when.get("audiences", ["*"]),
            "tools": when.get("tools", ["*"]),
            "execution_locations": (
                [when["tool.execution_location"]]
                if "tool.execution_location" in when
                else when.get("execution_locations", [])
            ),
        }
    return PrivacyPolicy(
        id=raw.get("id") or ids.new_id("pol"),
        name=raw.get("name", ""),
        effect=PolicyEffect(raw.get("effect", "deny")),
        priority=int(raw.get("priority", 100)),
        enabled=bool(raw.get("enabled", True)),
        overrideable=bool(raw.get("overrideable", True)),
        constitutional=bool(raw.get("constitutional", False)),
        subjects=PolicySubjects(**{
            k: v if isinstance(v, list) else [v] for k, v in {
                "personas": subjects.get("personas", ["*"]),
                "principals": subjects.get("principals", ["*"]),
            }.items()
        }),
        resources=PolicyResources(
            domains=list(resources.get("domains") or []),
            sensitivity=list(resources.get("sensitivity") or []),
            labels=list(resources.get("labels") or []),
            source_owners=list(resources.get("source_owners") or []),
            vaults=list(resources.get("vaults") or []),
            third_party=resources.get("third_party"),
        ),
        context=PolicyContext(
            purposes=list(context.get("purposes") or ["*"]),
            audiences=list(context.get("audiences") or ["*"]),
            tools=list(context.get("tools") or ["*"]),
            execution_locations=list(context.get("execution_locations") or []),
        ),
        obligations=list(raw.get("obligations") or []),
        reason=raw.get("reason", ""),
        created_at=raw.get("created_at") or now_iso(),
        version=int(raw.get("version", 1)),
    )


def resolve_tool(tool_id: str, *, store: Optional[MemoryStore] = None) -> Optional[ToolIdentity]:
    if store is not None and hasattr(store, "get_tool_identity"):
        t = store.get_tool_identity(tool_id)
        if t is not None:
            return t
    return DEFAULT_TOOLS.get(tool_id)


def bootstrap_policy_set(store: MemoryStore, *, actor: str = "system") -> PolicySetVersion:
    """Persist builtin policies as immutable revisions and activate a policy set."""
    from .identity import ensure_local_identity
    from .models import PrivacyPolicyRevision

    ensure_local_identity(store)
    policies = builtin_governance_policies()
    # Also import YAML if present — as revisions, not ad-hoc runtime mix
    # (YAML path handled by caller via load when bootstrapping workspace)

    revision_ids: list[str] = []
    policy_ids: list[str] = []
    for p in policies:
        existing = store.get_privacy_policy(p.id) if hasattr(store, "get_privacy_policy") else None
        if existing is None:
            store.insert_privacy_policy(p)
        # Always append an immutable revision for this bootstrap payload
        rev = PrivacyPolicyRevision(
            id=ids.new_id("prev"),
            policy_id=p.id,
            version=p.version,
            payload=p.model_dump(mode="json"),
            created_at=now_iso(),
            actor=actor,
            reason="bootstrap",
        )
        # Dedupe: if identical payload revision already in active set, reuse
        store.insert_privacy_policy_revision(rev)
        revision_ids.append(rev.id)
        policy_ids.append(p.id)

    parent = store.get_active_policy_set_version()
    if parent and set(parent.revision_ids or []) and set(parent.policy_ids) == set(policy_ids):
        # Still refresh if revision_ids empty (legacy)
        if parent.revision_ids:
            return parent
    store.deactivate_policy_set_versions()
    version = PolicySetVersion(
        id=ids.new_id("psv"),
        version=(parent.version + 1) if parent else 1,
        created_at=now_iso(),
        reason="bootstrap governance policies",
        policy_ids=policy_ids,
        revision_ids=revision_ids,
        active=True,
        actor=actor,
    )
    store.insert_policy_set_version(version)
    return version


def load_active_policy_revisions(store: MemoryStore) -> list[PrivacyPolicy]:
    """Load policies exclusively from the active PolicySetVersion revisions."""
    version = store.get_active_policy_set_version() if hasattr(store, "get_active_policy_set_version") else None
    if version and version.revision_ids and hasattr(store, "get_privacy_policy_revision"):
        out: list[PrivacyPolicy] = []
        for rid in version.revision_ids:
            rev = store.get_privacy_policy_revision(rid)
            if rev and rev.payload:
                out.append(PrivacyPolicy.model_validate(rev.payload))
        if out:
            return out
    # Fallback for stores without revisions yet
    return load_governance_policies(store=store)


def export_governance_yaml(store: MemoryStore) -> str:
    policies = store.list_privacy_policies() if hasattr(store, "list_privacy_policies") else []
    payload = {
        "governance": [
            {
                "id": p.id,
                "name": p.name,
                "effect": p.effect.value,
                "priority": p.priority,
                "constitutional": p.constitutional,
                "subjects": p.subjects.model_dump(),
                "resources": p.resources.model_dump(),
                "context": p.context.model_dump(),
                "reason": p.reason,
                "obligations": p.obligations,
            }
            for p in policies
        ]
    }
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)
