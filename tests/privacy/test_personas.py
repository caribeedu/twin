"""Persona records + judgment snapshot explain."""

from twin.privacy.identity import ensure_local_identity, resolve_access


def test_bootstrap_personas(store):
    ensure_local_identity(store)
    personas = {p.id: p for p in store.list_personas()}
    assert "developer" in personas
    assert "private_individual" in personas
    assert "vault_work" in personas["developer"].vault_ids
    assert "vault_personal" in personas["private_individual"].vault_ids


def test_implicit_persona_defaults_to_individual(store):
    """Alphabetically sorted allowlists put developer first; default must not."""
    from twin.privacy.identity import register_client_binding
    from twin.privacy.models import Principal, PrincipalType
    from twin.privacy.yaml_io import bootstrap_policy_set

    bootstrap_policy_set(store)
    ensure_local_identity(store)
    store.insert_principal(Principal(
        id="principal_dual_persona", type=PrincipalType.tool, name="dual",
        capabilities=["connector:read", "read_context_pack"],
        allowed_personas=["individual", "developer"],
        allowed_vaults=["vault_general", "vault_personal"],
    ))
    register_client_binding(
        store, client_id="dual-client", tool_id="dual-client",
        principal_id="principal_dual_persona", credential="tok-dual",
        capabilities=["connector:read"],
        allowed_personas=["individual", "developer"],
        allowed_vaults=["vault_general", "vault_personal"],
    )
    access = resolve_access(
        store, surface="mcp", client="dual-client", api_token="tok-dual",
    )
    assert access.persona == "individual"
    assert "vault_personal" in (access.metadata.get("allowed_vaults") or [])


def test_persona_restricts_domains_never_amplifies(store):
    ensure_local_identity(store)
    # employee persona + finance request → empty intersect → restricted
    access = resolve_access(
        store, surface="cli", client="local-cli",
        persona="employee", purpose="memory_retrieval", audience="self",
        requested_domains=["finance"],
    )
    assert access.principal_id == "unknown" or access.is_restricted_mode

    ok = resolve_access(
        store, surface="cli", client="local-cli",
        persona="developer", purpose="memory_retrieval", audience="self",
        requested_domains=["technical"],
    )
    assert ok.principal_id == "principal_local_cli"
    assert ok.persona == "developer"
    assert "technical" in ok.requested_domains
    assert "vault_work" in (ok.metadata.get("allowed_vaults") or [])
    # persona cannot grant vault_restricted to developer
    assert "vault_restricted" not in (ok.metadata.get("allowed_vaults") or [])


def test_private_individual_caps_restrict(store):
    ensure_local_identity(store)
    access = resolve_access(
        store, surface="cli", client="local-cli",
        persona="private_individual", purpose="memory_retrieval", audience="self",
        requested_domains=["personal_preferences"],
    )
    caps = set(access.metadata.get("resolved_capabilities") or [])
    assert "read:vault:vault_work" not in caps
    assert "vault_work" not in (access.metadata.get("allowed_vaults") or [])


def test_explain_judgment_snapshot(store):
    from twin import ids
    from twin.clock import now_iso
    from twin.judgment.explain import explain_judgment_snapshot
    from twin.judgment.models import AppliedRevisionRef, JudgmentSnapshot

    ensure_local_identity(store)
    snap = JudgmentSnapshot(
        id=ids.new_id("jsnap"),
        judgment_version_id="jv_test",
        applied_revisions=[
            AppliedRevisionRef(
                judgment_id="j_1", revision_id="jr_missing", effective_strength=0.8,
            ),
        ],
        target_domain="technical",
        persona="developer",
        created_at=now_iso(),
    )
    store.insert_judgment_snapshot(snap)
    explained = explain_judgment_snapshot(store, snap.id)
    assert explained["snapshot_id"] == snap.id
    assert explained["persona"] == "developer"
    assert len(explained["applied_revisions"]) == 1
