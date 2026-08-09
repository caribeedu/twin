"""Cognize entity store mixin (Twin v2 Narratives / Reflections / …)."""

from __future__ import annotations

from typing import Any, Optional

from twin.cognize.models import (
    EpistemicState,
    EpistemicStatus,
    EvidenceAnchor,
    Interpretation,
    Narrative,
    NarrativeRevisionDecision,
    Reflection,
    Relation,
    Situation,
    Trace,
)
from twin.cognize.persistence import (
    epistemic_state_to_row,
    evidence_anchor_to_row,
    interpretation_to_row,
    narrative_revision_to_row,
    narrative_to_row,
    reflection_to_row,
    relation_to_row,
    row_to_epistemic_state,
    row_to_evidence_anchor,
    row_to_interpretation,
    row_to_narrative,
    row_to_narrative_revision,
    row_to_reflection,
    row_to_relation,
    row_to_situation,
    row_to_trace,
    situation_to_row,
    trace_to_row,
)

COGNIZE_SCHEMA = """
CREATE TABLE IF NOT EXISTS cognize_situations (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'working',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cog_sit_vault ON cognize_situations(vault_id);

CREATE TABLE IF NOT EXISTS cognize_reflections (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cog_ref_vault ON cognize_reflections(vault_id);
CREATE INDEX IF NOT EXISTS idx_cog_ref_status ON cognize_reflections(vault_id, status);

CREATE TABLE IF NOT EXISTS cognize_interpretations (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'competing',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cog_intp_vault ON cognize_interpretations(vault_id);

CREATE TABLE IF NOT EXISTS cognize_relations (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL,
    from_id TEXT NOT NULL,
    to_id TEXT NOT NULL,
    type TEXT NOT NULL,
    asserted_by TEXT NOT NULL DEFAULT 'llm',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cog_rel_vault ON cognize_relations(vault_id);
CREATE INDEX IF NOT EXISTS idx_cog_rel_type ON cognize_relations(vault_id, type);
CREATE INDEX IF NOT EXISTS idx_cog_rel_from ON cognize_relations(from_id);
CREATE INDEX IF NOT EXISTS idx_cog_rel_to ON cognize_relations(to_id);

CREATE TABLE IF NOT EXISTS cognize_epistemic_states (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL DEFAULT 'fresh',
    payload TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS cognize_narratives (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'committed',
    epistemic_state_id TEXT NOT NULL DEFAULT '',
    domain TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cog_nar_vault ON cognize_narratives(vault_id);
CREATE INDEX IF NOT EXISTS idx_cog_nar_eps ON cognize_narratives(epistemic_state_id);

CREATE TABLE IF NOT EXISTS cognize_evidence_anchors (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL,
    percept_id TEXT NOT NULL,
    target_kind TEXT NOT NULL DEFAULT '',
    target_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cog_evac_vault ON cognize_evidence_anchors(vault_id);
CREATE INDEX IF NOT EXISTS idx_cog_evac_target
    ON cognize_evidence_anchors(target_kind, target_id);

CREATE TABLE IF NOT EXISTS cognize_traces (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL DEFAULT '',
    event_kind TEXT NOT NULL,
    resource_kind TEXT NOT NULL DEFAULT '',
    resource_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cog_trc_resource
    ON cognize_traces(resource_kind, resource_id);

CREATE TABLE IF NOT EXISTS cognize_narrative_revisions (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL DEFAULT '',
    outcome TEXT NOT NULL,
    prior_narrative_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_cog_nrev_vault ON cognize_narrative_revisions(vault_id);
"""


class CognizeStoreMixin:
    """Duck-typed persistence for Cognize entities."""

    def _cog_dec(self, payload: Any) -> Any:
        if hasattr(self, "codec") and self.codec is not None:
            try:
                return self.codec.decrypt(payload) if isinstance(payload, str) else payload
            except Exception:
                return payload
        return payload

    def _cog_enc_row(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        if "payload" in out and hasattr(self, "codec"):
            out["payload"] = self.codec.encrypt(out["payload"])
        return out

    def _cog_upsert(self, table: str, entity_id: str, row: dict[str, Any]) -> None:
        existing = self._j_fetchone(f"SELECT id FROM {table} WHERE id = ?", (entity_id,))
        enc = self._cog_enc_row(row)
        if existing:
            self._c_update(table, entity_id, enc)
        else:
            self._c_insert(table, enc)

    # --- Situation ---

    def upsert_situation(self, obj: Situation) -> str:
        self._cog_upsert("cognize_situations", obj.id, situation_to_row(obj))
        return obj.id

    def get_situation(self, sit_id: str) -> Optional[Situation]:
        row = self._j_fetchone(
            "SELECT * FROM cognize_situations WHERE id = ?", (sit_id,)
        )
        return row_to_situation(row, decrypt=self._cog_dec) if row else None

    def list_situations(self, vault_id: str) -> list[Situation]:
        rows = self._j_fetchall(
            "SELECT * FROM cognize_situations WHERE vault_id = ?", (vault_id,)
        )
        return [row_to_situation(r, decrypt=self._cog_dec) for r in rows]

    # --- Reflection ---

    def upsert_reflection(self, obj: Reflection) -> str:
        self._cog_upsert("cognize_reflections", obj.id, reflection_to_row(obj))
        return obj.id

    def get_reflection(self, ref_id: str) -> Optional[Reflection]:
        row = self._j_fetchone(
            "SELECT * FROM cognize_reflections WHERE id = ?", (ref_id,)
        )
        return row_to_reflection(row, decrypt=self._cog_dec) if row else None

    def list_open_reflections(self, vault_id: str) -> list[Reflection]:
        rows = self._j_fetchall(
            "SELECT * FROM cognize_reflections WHERE vault_id = ? AND status = ?",
            (vault_id, "open"),
        )
        return [row_to_reflection(r, decrypt=self._cog_dec) for r in rows]

    # --- Interpretation ---

    def upsert_interpretation(self, obj: Interpretation) -> str:
        self._cog_upsert(
            "cognize_interpretations", obj.id, interpretation_to_row(obj)
        )
        return obj.id

    def get_interpretation(self, intp_id: str) -> Optional[Interpretation]:
        row = self._j_fetchone(
            "SELECT * FROM cognize_interpretations WHERE id = ?", (intp_id,)
        )
        return row_to_interpretation(row, decrypt=self._cog_dec) if row else None

    # --- Relation ---

    def upsert_relation(self, obj: Relation) -> str:
        self._cog_upsert("cognize_relations", obj.id, relation_to_row(obj))
        return obj.id

    def list_relations(
        self,
        vault_id: str,
        *,
        rel_type: Optional[str] = None,
    ) -> list[Relation]:
        if rel_type:
            rows = self._j_fetchall(
                "SELECT * FROM cognize_relations WHERE vault_id = ? AND type = ?",
                (vault_id, rel_type),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM cognize_relations WHERE vault_id = ?",
                (vault_id,),
            )
        return [row_to_relation(r, decrypt=self._cog_dec) for r in rows]

    # --- EpistemicState ---

    def upsert_epistemic_state(self, obj: EpistemicState) -> str:
        self._cog_upsert(
            "cognize_epistemic_states", obj.id, epistemic_state_to_row(obj)
        )
        return obj.id

    def get_epistemic_state(self, eps_id: str) -> Optional[EpistemicState]:
        row = self._j_fetchone(
            "SELECT * FROM cognize_epistemic_states WHERE id = ?", (eps_id,)
        )
        return row_to_epistemic_state(row, decrypt=self._cog_dec) if row else None

    def mark_epistemic_stale(
        self,
        eps_id: str,
        *,
        reason: str,
        unseen_percept_id: str,
    ) -> Optional[EpistemicState]:
        """Deterministic stale latch — no LLM."""
        eps = self.get_epistemic_state(eps_id)
        if eps is None:
            return None
        unseen = list(eps.unseen_since)
        if unseen_percept_id and unseen_percept_id not in unseen:
            unseen.append(unseen_percept_id)
        updated = eps.model_copy(
            update={
                "status": EpistemicStatus.stale,
                "stale_reason": reason,
                "unseen_since": unseen,
            }
        )
        self.upsert_epistemic_state(updated)
        return updated

    # --- Narrative ---

    def upsert_narrative(self, obj: Narrative) -> str:
        self._cog_upsert("cognize_narratives", obj.id, narrative_to_row(obj))
        return obj.id

    def get_narrative(self, nar_id: str) -> Optional[Narrative]:
        row = self._j_fetchone(
            "SELECT * FROM cognize_narratives WHERE id = ?", (nar_id,)
        )
        return row_to_narrative(row, decrypt=self._cog_dec) if row else None

    def list_narratives(self, vault_id: str) -> list[Narrative]:
        rows = self._j_fetchall(
            "SELECT * FROM cognize_narratives WHERE vault_id = ?", (vault_id,)
        )
        return [row_to_narrative(r, decrypt=self._cog_dec) for r in rows]

    # --- Evidence + Trace + Revision ---

    def upsert_evidence_anchor(self, obj: EvidenceAnchor) -> str:
        self._cog_upsert(
            "cognize_evidence_anchors", obj.id, evidence_anchor_to_row(obj)
        )
        return obj.id

    def append_trace(self, obj: Trace) -> str:
        # Traces are append-only — never update in place.
        self._c_insert("cognize_traces", self._cog_enc_row(trace_to_row(obj)))
        return obj.id

    def upsert_narrative_revision(self, obj: NarrativeRevisionDecision) -> str:
        self._cog_upsert(
            "cognize_narrative_revisions", obj.id, narrative_revision_to_row(obj)
        )
        return obj.id

    def get_narrative_revision(
        self, rev_id: str
    ) -> Optional[NarrativeRevisionDecision]:
        row = self._j_fetchone(
            "SELECT * FROM cognize_narrative_revisions WHERE id = ?", (rev_id,)
        )
        return row_to_narrative_revision(row, decrypt=self._cog_dec) if row else None
