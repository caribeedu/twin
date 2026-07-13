"""Privacy/governance store mixin — shared CRUD for SQLite and Postgres."""

from __future__ import annotations

from typing import Any, Optional

from twin.privacy.models import (
    ConsentRecord,
    DeletionRequest,
    ExportRecord,
    LeakageCanary,
    PermissionGrant,
    PolicySetVersion,
    Principal,
    PrivacyDecision,
    PrivacyPolicy,
    QuarantineRecord,
    RedactionPlan,
    ToolIdentity,
    Vault,
)
from twin.privacy.persistence import (
    canary_to_row,
    consent_to_row,
    decision_to_row,
    deletion_to_row,
    export_to_row,
    grant_to_row,
    policy_set_to_row,
    policy_to_row,
    principal_to_row,
    quarantine_to_row,
    redaction_to_row,
    row_to_canary,
    row_to_consent,
    row_to_decision,
    row_to_deletion,
    row_to_export,
    row_to_grant,
    row_to_policy,
    row_to_policy_set,
    row_to_principal,
    row_to_quarantine,
    row_to_redaction,
    row_to_tool,
    row_to_vault,
    tool_to_row,
    vault_to_row,
)


class PrivacyStoreMixin:
    """Duck-typed privacy persistence. Mix into SqliteStore / PostgresStore."""

    def _p_insert(self, table: str, row: dict[str, Any]) -> None:
        cols = list(row.keys())
        ph = ", ".join("?" for _ in cols)
        self._j_exec(
            f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({ph})",
            tuple(row[c] for c in cols),
        )
        self._j_commit()

    def _p_update_payload(self, table: str, entity_id: str, payload: dict[str, Any],
                          **cols: Any) -> None:
        sets = ["payload = ?"]
        vals: list[Any] = [__import__("json").dumps(payload, default=str)]
        for k, v in cols.items():
            sets.append(f"{k} = ?")
            vals.append(v)
        vals.append(entity_id)
        self._j_exec(
            f"UPDATE {table} SET {', '.join(sets)} WHERE id = ?",
            tuple(vals),
        )
        self._j_commit()

    # -- policies ---------------------------------------------------------

    def insert_privacy_policy(self, policy: PrivacyPolicy) -> str:
        self._p_insert("privacy_policies", policy_to_row(policy))
        return policy.id

    def get_privacy_policy(self, policy_id: str) -> Optional[PrivacyPolicy]:
        row = self._j_fetchone("SELECT * FROM privacy_policies WHERE id = ?", (policy_id,))
        return row_to_policy(row) if row else None

    def list_privacy_policies(self, enabled: Optional[bool] = None) -> list[PrivacyPolicy]:
        if enabled is None:
            rows = self._j_fetchall("SELECT * FROM privacy_policies ORDER BY priority DESC", ())
        else:
            rows = self._j_fetchall(
                "SELECT * FROM privacy_policies WHERE enabled = ? ORDER BY priority DESC",
                (1 if enabled else 0,),
            )
        return [row_to_policy(r) for r in rows]

    def insert_policy_set_version(self, version: PolicySetVersion) -> str:
        self._p_insert("privacy_policy_sets", policy_set_to_row(version))
        return version.id

    def deactivate_policy_set_versions(self) -> None:
        self._j_exec("UPDATE privacy_policy_sets SET active = 0 WHERE active != 0", ())
        self._j_commit()

    def get_active_policy_set_version(self) -> Optional[PolicySetVersion]:
        row = self._j_fetchone(
            "SELECT * FROM privacy_policy_sets WHERE active != 0 ORDER BY version DESC LIMIT 1",
            (),
        )
        return row_to_policy_set(row) if row else None

    # -- decisions --------------------------------------------------------

    def insert_privacy_decision(self, decision: PrivacyDecision) -> str:
        self._p_insert("privacy_decisions", decision_to_row(decision))
        return decision.id

    def get_privacy_decision(self, decision_id: str) -> Optional[PrivacyDecision]:
        row = self._j_fetchone("SELECT * FROM privacy_decisions WHERE id = ?", (decision_id,))
        return row_to_decision(row) if row else None

    # -- grants -----------------------------------------------------------

    def insert_permission_grant(self, grant: PermissionGrant) -> str:
        self._p_insert("permission_grants", grant_to_row(grant))
        return grant.id

    def get_permission_grant(self, grant_id: str) -> Optional[PermissionGrant]:
        row = self._j_fetchone("SELECT * FROM permission_grants WHERE id = ?", (grant_id,))
        return row_to_grant(row) if row else None

    def list_permission_grants(self, status: Optional[str] = None) -> list[PermissionGrant]:
        if status:
            rows = self._j_fetchall(
                "SELECT * FROM permission_grants WHERE status = ? ORDER BY valid_from DESC",
                (status,),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM permission_grants ORDER BY valid_from DESC", (),
            )
        return [row_to_grant(r) for r in rows]

    def update_permission_grant(self, grant_id: str, **fields: Any) -> None:
        g = self.get_permission_grant(grant_id)
        if g is None:
            raise ValueError(f"grant {grant_id} not found")
        data = g.model_dump(mode="json")
        data.update(fields)
        updated = PermissionGrant.model_validate(data)
        row = grant_to_row(updated)
        cols = [c for c in row if c != "id"]
        sets = ", ".join(f"{c} = ?" for c in cols)
        self._j_exec(
            f"UPDATE permission_grants SET {sets} WHERE id = ?",
            tuple(row[c] for c in cols) + (grant_id,),
        )
        self._j_commit()

    def consume_permission_grant(
        self, grant_id: str, *, expected_version: Optional[int] = None,
    ) -> bool:
        """Compare-and-set use increment. Returns False on conflict."""
        g = self.get_permission_grant(grant_id)
        if g is None:
            return False
        if expected_version is not None and g.version != expected_version:
            return False
        if g.status.value != "active":
            return False
        if g.max_uses is not None and g.uses >= g.max_uses:
            return False
        from twin.clock import now_iso
        if g.valid_until and g.valid_until < now_iso():
            self.update_permission_grant(grant_id, status="expired")
            return False
        new_uses = g.uses + 1
        new_status = "exhausted" if (g.max_uses is not None and new_uses >= g.max_uses) else "active"
        # Optimistic: update only if version still matches
        cur = self._j_exec(
            "UPDATE permission_grants SET uses = ?, version = ?, status = ?, payload = ?"
            " WHERE id = ? AND version = ?",
            (
                new_uses, g.version + 1, new_status,
                __import__("json").dumps({
                    **g.model_dump(mode="json"),
                    "uses": new_uses,
                    "version": g.version + 1,
                    "status": new_status,
                }, default=str),
                grant_id, g.version,
            ),
        )
        self._j_commit()
        # sqlite rowcount via cursor if available
        rowcount = getattr(cur, "rowcount", None)
        if rowcount is None:
            # re-read
            after = self.get_permission_grant(grant_id)
            return after is not None and after.uses == new_uses
        return rowcount > 0

    # -- consent / quarantine / canary / deletion / export ----------------

    def insert_consent(self, consent: ConsentRecord) -> str:
        self._p_insert("consent_records", consent_to_row(consent))
        return consent.id

    def list_consents(self, status: Optional[str] = None) -> list[ConsentRecord]:
        if status:
            rows = self._j_fetchall(
                "SELECT * FROM consent_records WHERE status = ?", (status,),
            )
        else:
            rows = self._j_fetchall("SELECT * FROM consent_records", ())
        return [row_to_consent(r) for r in rows]

    def insert_quarantine(self, record: QuarantineRecord) -> str:
        self._p_insert("quarantine_records", quarantine_to_row(record))
        return record.id

    def get_quarantine(self, quarantine_id: str) -> Optional[QuarantineRecord]:
        row = self._j_fetchone(
            "SELECT * FROM quarantine_records WHERE id = ?", (quarantine_id,),
        )
        return row_to_quarantine(row) if row else None

    def find_quarantine_by_fingerprint(self, fp: str) -> Optional[QuarantineRecord]:
        row = self._j_fetchone(
            "SELECT * FROM quarantine_records WHERE content_fingerprint = ?"
            " AND status = 'quarantined' LIMIT 1",
            (fp,),
        )
        return row_to_quarantine(row) if row else None

    def list_quarantine(self, status: Optional[str] = None) -> list[QuarantineRecord]:
        if status:
            rows = self._j_fetchall(
                "SELECT * FROM quarantine_records WHERE status = ? ORDER BY created_at DESC",
                (status,),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM quarantine_records ORDER BY created_at DESC", (),
            )
        return [row_to_quarantine(r) for r in rows]

    def update_quarantine(self, quarantine_id: str, **fields: Any) -> None:
        q = self.get_quarantine(quarantine_id)
        if q is None:
            raise ValueError(f"quarantine {quarantine_id} not found")
        data = q.model_dump(mode="json")
        data.update(fields)
        updated = QuarantineRecord.model_validate(data)
        row = quarantine_to_row(updated)
        self._j_exec(
            "UPDATE quarantine_records SET status = ?, payload = ? WHERE id = ?",
            (row["status"], row["payload"], quarantine_id),
        )
        self._j_commit()

    def insert_leakage_canary(self, canary: LeakageCanary) -> str:
        self._p_insert("leakage_canaries", canary_to_row(canary))
        return canary.id

    def list_leakage_canaries(self, active: Optional[bool] = None) -> list[LeakageCanary]:
        if active is None:
            rows = self._j_fetchall("SELECT * FROM leakage_canaries", ())
        else:
            rows = self._j_fetchall(
                "SELECT * FROM leakage_canaries WHERE active = ?",
                (1 if active else 0,),
            )
        return [row_to_canary(r) for r in rows]

    def insert_deletion_request(self, req: DeletionRequest) -> str:
        self._p_insert("deletion_requests", deletion_to_row(req))
        return req.id

    def get_deletion_request(self, deletion_id: str) -> Optional[DeletionRequest]:
        row = self._j_fetchone("SELECT * FROM deletion_requests WHERE id = ?", (deletion_id,))
        return row_to_deletion(row) if row else None

    def update_deletion_request(self, deletion_id: str, **fields: Any) -> None:
        req = self.get_deletion_request(deletion_id)
        if req is None:
            raise ValueError(f"deletion {deletion_id} not found")
        data = req.model_dump(mode="json")
        data.update(fields)
        updated = DeletionRequest.model_validate(data)
        row = deletion_to_row(updated)
        self._j_exec(
            "UPDATE deletion_requests SET status = ?, payload = ? WHERE id = ?",
            (row["status"], row["payload"], deletion_id),
        )
        self._j_commit()

    def insert_export_record(self, export: ExportRecord) -> str:
        self._p_insert("export_records", export_to_row(export))
        return export.id

    def insert_redaction_plan(self, plan: RedactionPlan) -> str:
        self._p_insert("redaction_plans", redaction_to_row(plan))
        return plan.id

    def insert_principal(self, principal: Principal) -> str:
        self._p_insert("privacy_principals", principal_to_row(principal))
        return principal.id

    def get_principal(self, principal_id: str) -> Optional[Principal]:
        row = self._j_fetchone(
            "SELECT * FROM privacy_principals WHERE id = ?", (principal_id,),
        )
        return row_to_principal(row) if row else None

    def insert_tool_identity(self, tool: ToolIdentity) -> str:
        self._p_insert("privacy_tools", tool_to_row(tool))
        return tool.id

    def get_tool_identity(self, tool_id: str) -> Optional[ToolIdentity]:
        row = self._j_fetchone("SELECT * FROM privacy_tools WHERE id = ?", (tool_id,))
        return row_to_tool(row) if row else None

    def insert_vault(self, vault: Vault) -> str:
        self._p_insert("privacy_vaults", vault_to_row(vault))
        return vault.id
