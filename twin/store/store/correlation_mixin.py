"""Cross-source correlation store mixin."""

from __future__ import annotations

from typing import Any, Optional

from twin.cognize.services.correlation.models import (
    EpisodeEdge,
    EpisodeLink,
    EpisodePhase,
    ExternalIdentity,
    IdentityLink,
    ProjectLink,
    WorkEpisode,
)
from twin.cognize.services.correlation.persistence import (
    episode_edge_to_row,
    episode_link_to_row,
    episode_phase_to_row,
    episode_to_row,
    identity_link_to_row,
    identity_to_row,
    project_link_to_row,
    row_to_episode,
    row_to_episode_edge,
    row_to_episode_link,
    row_to_episode_phase,
    row_to_identity,
    row_to_identity_link,
    row_to_project_link,
)
from twin import ids

CORRELATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS external_identities (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_account_id TEXT NOT NULL DEFAULT '',
    vault_id TEXT NOT NULL DEFAULT '',
    actor_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_extid_acct
    ON external_identities(provider, external_id, source_account_id);
CREATE INDEX IF NOT EXISTS idx_extid_vault ON external_identities(vault_id);
CREATE INDEX IF NOT EXISTS idx_extid_actor ON external_identities(actor_id);

CREATE TABLE IF NOT EXISTS identity_links (
    id TEXT PRIMARY KEY,
    left_identity_id TEXT NOT NULL,
    right_identity_id TEXT NOT NULL DEFAULT '',
    vault_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'candidate',
    payload TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_idlink_pair
    ON identity_links(left_identity_id, right_identity_id);
CREATE INDEX IF NOT EXISTS idx_idlink_vault ON identity_links(vault_id);

CREATE TABLE IF NOT EXISTS project_links (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    external_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_account_id TEXT NOT NULL DEFAULT '',
    vault_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_projlink_ext
    ON project_links(source_account_id, external_type, external_id);
CREATE INDEX IF NOT EXISTS idx_projlink_vault ON project_links(vault_id);

CREATE TABLE IF NOT EXISTS work_episodes (
    id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL DEFAULT '',
    correlation_key TEXT NOT NULL DEFAULT '',
    project_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'candidate',
    independence_group TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_episode_corr
    ON work_episodes(vault_id, correlation_key)
    WHERE correlation_key != '';
CREATE INDEX IF NOT EXISTS idx_episode_vault ON work_episodes(vault_id);
CREATE INDEX IF NOT EXISTS idx_episode_indep
    ON work_episodes(vault_id, independence_group);

CREATE TABLE IF NOT EXISTS episode_links (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    vault_id TEXT NOT NULL DEFAULT '',
    external_type TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'soft',
    status TEXT NOT NULL DEFAULT 'active',
    payload TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_eplink_member
    ON episode_links(episode_id, external_type, external_id);
CREATE INDEX IF NOT EXISTS idx_eplink_episode ON episode_links(episode_id);
CREATE INDEX IF NOT EXISTS idx_eplink_vault ON episode_links(vault_id);

CREATE TABLE IF NOT EXISTS episode_anchors (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    vault_id TEXT NOT NULL,
    anchor_type TEXT NOT NULL,
    anchor_value TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_ep_anchor
    ON episode_anchors(vault_id, anchor_type, anchor_value);
CREATE INDEX IF NOT EXISTS idx_ep_anchor_episode ON episode_anchors(episode_id);

CREATE TABLE IF NOT EXISTS episode_phases (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    vault_id TEXT NOT NULL DEFAULT '',
    phase_key TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'other',
    status TEXT NOT NULL DEFAULT 'proposed',
    ordinal INTEGER NOT NULL DEFAULT 0,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_epphase_episode ON episode_phases(episode_id);
CREATE INDEX IF NOT EXISTS idx_epphase_vault ON episode_phases(vault_id);

CREATE TABLE IF NOT EXISTS episode_edges (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    vault_id TEXT NOT NULL DEFAULT '',
    relation TEXT NOT NULL DEFAULT 'continues',
    status TEXT NOT NULL DEFAULT 'proposed',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_epedge_episode ON episode_edges(episode_id);
CREATE INDEX IF NOT EXISTS idx_epedge_vault ON episode_edges(vault_id);

CREATE TABLE IF NOT EXISTS correlation_dirty (
    connector_record_id TEXT PRIMARY KEY,
    vault_id TEXT NOT NULL DEFAULT '',
    reason TEXT NOT NULL DEFAULT '',
    marked_at TEXT NOT NULL DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_corr_dirty_vault ON correlation_dirty(vault_id);
"""


class CorrelationStoreMixin:
    """Duck-typed persistence for correlation objects."""

    def _corr_dec(self, payload: Any) -> Any:
        if hasattr(self, "codec") and self.codec is not None:
            try:
                return self.codec.decrypt(payload) if isinstance(payload, str) else payload
            except Exception:
                return payload
        return payload

    def _corr_enc_row(self, row: dict[str, Any]) -> dict[str, Any]:
        out = dict(row)
        if "payload" in out and hasattr(self, "codec"):
            out["payload"] = self.codec.encrypt(out["payload"])
        return out

    def insert_external_identity(self, ident: ExternalIdentity) -> str:
        self._c_insert(
            "external_identities", self._corr_enc_row(identity_to_row(ident)),
        )
        return ident.id

    def update_external_identity(self, ident: ExternalIdentity) -> None:
        self._c_update(
            "external_identities", ident.id,
            self._corr_enc_row(identity_to_row(ident)),
        )

    def get_external_identity(self, ident_id: str) -> Optional[ExternalIdentity]:
        row = self._j_fetchone(
            "SELECT * FROM external_identities WHERE id = ?", (ident_id,),
        )
        return row_to_identity(row, decrypt=self._corr_dec) if row else None

    def find_external_identity(
        self,
        *,
        provider: str,
        external_id: str,
        source_account_id: Optional[str] = None,
    ) -> Optional[ExternalIdentity]:
        if source_account_id:
            row = self._j_fetchone(
                "SELECT * FROM external_identities WHERE provider = ? AND "
                "external_id = ? AND source_account_id = ?",
                (provider, external_id, source_account_id),
            )
        else:
            row = self._j_fetchone(
                "SELECT * FROM external_identities WHERE provider = ? AND "
                "external_id = ? ORDER BY id LIMIT 1",
                (provider, external_id),
            )
        return row_to_identity(row, decrypt=self._corr_dec) if row else None

    def list_external_identities(
        self, *, provider: Optional[str] = None, vault_id: Optional[str] = None,
    ) -> list[ExternalIdentity]:
        if provider and vault_id:
            rows = self._j_fetchall(
                "SELECT * FROM external_identities WHERE provider = ? AND "
                "vault_id = ? ORDER BY id",
                (provider, vault_id),
            )
        elif provider:
            rows = self._j_fetchall(
                "SELECT * FROM external_identities WHERE provider = ? ORDER BY id",
                (provider,),
            )
        elif vault_id:
            rows = self._j_fetchall(
                "SELECT * FROM external_identities WHERE vault_id = ? ORDER BY id",
                (vault_id,),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM external_identities ORDER BY id", (),
            )
        return [row_to_identity(r, decrypt=self._corr_dec) for r in rows]

    def insert_identity_link(self, link: IdentityLink) -> str:
        self._c_insert(
            "identity_links", self._corr_enc_row(identity_link_to_row(link)),
        )
        return link.id

    def update_identity_link(self, link: IdentityLink) -> None:
        self._c_update(
            "identity_links", link.id,
            self._corr_enc_row(identity_link_to_row(link)),
        )

    def get_identity_link(self, link_id: str) -> Optional[IdentityLink]:
        row = self._j_fetchone(
            "SELECT * FROM identity_links WHERE id = ?", (link_id,),
        )
        return row_to_identity_link(row, decrypt=self._corr_dec) if row else None

    def find_identity_link(
        self, left_id: str, right_id: str,
    ) -> Optional[IdentityLink]:
        row = self._j_fetchone(
            "SELECT * FROM identity_links WHERE "
            "(left_identity_id = ? AND right_identity_id = ?) OR "
            "(left_identity_id = ? AND right_identity_id = ?)",
            (left_id, right_id, right_id, left_id),
        )
        return row_to_identity_link(row, decrypt=self._corr_dec) if row else None

    def list_identity_links(self, *, vault_id: Optional[str] = None) -> list[IdentityLink]:
        if vault_id:
            rows = self._j_fetchall(
                "SELECT * FROM identity_links WHERE vault_id = ? ORDER BY id",
                (vault_id,),
            )
        else:
            rows = self._j_fetchall("SELECT * FROM identity_links ORDER BY id", ())
        return [row_to_identity_link(r, decrypt=self._corr_dec) for r in rows]

    def insert_project_link(self, link: ProjectLink) -> str:
        self._c_insert(
            "project_links", self._corr_enc_row(project_link_to_row(link)),
        )
        return link.id

    def update_project_link(self, link: ProjectLink) -> None:
        self._c_update(
            "project_links", link.id,
            self._corr_enc_row(project_link_to_row(link)),
        )

    def get_project_link(self, link_id: str) -> Optional[ProjectLink]:
        row = self._j_fetchone(
            "SELECT * FROM project_links WHERE id = ?", (link_id,),
        )
        return row_to_project_link(row, decrypt=self._corr_dec) if row else None

    def find_project_link(
        self,
        *,
        external_type: str,
        external_id: str,
        source_account_id: str = "",
    ) -> Optional[ProjectLink]:
        """Exact account match — including legacy unscoped ``""``.

        Never wildcards across accounts. Pass ``source_account_id=""`` to find
        only links created without an account scope.
        """
        row = self._j_fetchone(
            "SELECT * FROM project_links WHERE external_type = ? AND "
            "external_id = ? AND source_account_id = ?",
            (external_type, external_id, source_account_id or ""),
        )
        return row_to_project_link(row, decrypt=self._corr_dec) if row else None

    def list_project_links(
        self, *, project_id: Optional[str] = None,
    ) -> list[ProjectLink]:
        if project_id:
            rows = self._j_fetchall(
                "SELECT * FROM project_links WHERE project_id = ? ORDER BY id",
                (project_id,),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM project_links ORDER BY id", (),
            )
        return [row_to_project_link(r, decrypt=self._corr_dec) for r in rows]

    def insert_work_episode(self, ep: WorkEpisode) -> str:
        self._c_insert("work_episodes", self._corr_enc_row(episode_to_row(ep)))
        return ep.id

    def update_work_episode(self, ep: WorkEpisode) -> None:
        self._c_update(
            "work_episodes", ep.id, self._corr_enc_row(episode_to_row(ep)),
        )

    def get_work_episode(self, episode_id: str) -> Optional[WorkEpisode]:
        row = self._j_fetchone(
            "SELECT * FROM work_episodes WHERE id = ?", (episode_id,),
        )
        return row_to_episode(row, decrypt=self._corr_dec) if row else None

    def find_work_episode_by_correlation_key(
        self, vault_id: str, correlation_key: str,
    ) -> Optional[WorkEpisode]:
        if not correlation_key:
            return None
        row = self._j_fetchone(
            "SELECT * FROM work_episodes WHERE vault_id = ? AND "
            "correlation_key = ? LIMIT 1",
            (vault_id, correlation_key),
        )
        return row_to_episode(row, decrypt=self._corr_dec) if row else None

    def find_work_episode_by_anchor(
        self, vault_id: str, anchor_type: str, anchor_value: str,
    ) -> Optional[WorkEpisode]:
        row = self._j_fetchone(
            "SELECT episode_id FROM episode_anchors WHERE vault_id = ? AND "
            "anchor_type = ? AND anchor_value = ? LIMIT 1",
            (vault_id, anchor_type, anchor_value),
        )
        if not row:
            return None
        eid = row["episode_id"] if hasattr(row, "keys") else row[0]
        return self.get_work_episode(eid)

    def list_episode_anchors(self, episode_id: str) -> list[dict[str, Any]]:
        rows = self._j_fetchall(
            "SELECT episode_id, vault_id, anchor_type, anchor_value "
            "FROM episode_anchors WHERE episode_id = ?",
            (episode_id,),
        )
        out: list[dict[str, Any]] = []
        for r in rows:
            if hasattr(r, "keys"):
                out.append({
                    "episode_id": r["episode_id"],
                    "vault_id": r["vault_id"],
                    "anchor_type": r["anchor_type"],
                    "anchor_value": r["anchor_value"],
                })
            else:
                out.append({
                    "episode_id": r[0],
                    "vault_id": r[1],
                    "anchor_type": r[2],
                    "anchor_value": r[3],
                })
        return out

    def upsert_episode_anchor(
        self,
        *,
        episode_id: str,
        vault_id: str,
        anchor_type: str,
        anchor_value: str,
    ) -> None:
        existing = self._j_fetchone(
            "SELECT id, episode_id FROM episode_anchors WHERE vault_id = ? AND "
            "anchor_type = ? AND anchor_value = ?",
            (vault_id, anchor_type, anchor_value),
        )
        if existing:
            eid = existing["episode_id"] if hasattr(existing, "keys") else existing[1]
            if eid != episode_id:
                self._j_exec(
                    "UPDATE episode_anchors SET episode_id = ? WHERE vault_id = ? "
                    "AND anchor_type = ? AND anchor_value = ?",
                    (episode_id, vault_id, anchor_type, anchor_value),
                )
                self._j_commit()
            return
        self._c_insert("episode_anchors", {
            "id": ids.new_id("epanch"),
            "episode_id": episode_id,
            "vault_id": vault_id,
            "anchor_type": anchor_type,
            "anchor_value": anchor_value,
        })

    def find_work_episode_by_lineage(
        self, lineage_root: str, *, vault_id: Optional[str] = None,
    ) -> Optional[WorkEpisode]:
        key = (
            f"lineage:{lineage_root}"
            if not str(lineage_root).startswith("lineage:")
            else lineage_root
        )
        if vault_id:
            row = self._j_fetchone(
                "SELECT * FROM work_episodes WHERE vault_id = ? AND "
                "independence_group = ? ORDER BY id LIMIT 1",
                (vault_id, key),
            )
            if row:
                return row_to_episode(row, decrypt=self._corr_dec)
            row = self._j_fetchone(
                "SELECT * FROM work_episodes WHERE vault_id = ? AND "
                "independence_group = ? ORDER BY id LIMIT 1",
                (vault_id, lineage_root),
            )
            return row_to_episode(row, decrypt=self._corr_dec) if row else None
        row = self._j_fetchone(
            "SELECT * FROM work_episodes WHERE independence_group = ? "
            "ORDER BY id LIMIT 1",
            (key,),
        )
        return row_to_episode(row, decrypt=self._corr_dec) if row else None

    def list_work_episodes(
        self,
        *,
        project_id: Optional[str] = None,
        vault_id: Optional[str] = None,
        limit: int = 200,
    ) -> list[WorkEpisode]:
        if vault_id and project_id:
            rows = self._j_fetchall(
                "SELECT * FROM work_episodes WHERE vault_id = ? AND "
                "project_id = ? ORDER BY id DESC LIMIT ?",
                (vault_id, project_id, limit),
            )
        elif vault_id:
            rows = self._j_fetchall(
                "SELECT * FROM work_episodes WHERE vault_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (vault_id, limit),
            )
        elif project_id:
            rows = self._j_fetchall(
                "SELECT * FROM work_episodes WHERE project_id = ? "
                "ORDER BY id DESC LIMIT ?",
                (project_id, limit),
            )
        else:
            rows = self._j_fetchall(
                "SELECT * FROM work_episodes ORDER BY id DESC LIMIT ?",
                (limit,),
            )
        return [row_to_episode(r, decrypt=self._corr_dec) for r in rows]

    def insert_episode_link(self, link: EpisodeLink) -> str:
        self._c_insert(
            "episode_links", self._corr_enc_row(episode_link_to_row(link)),
        )
        return link.id

    def update_episode_link(self, link: EpisodeLink) -> None:
        self._c_update(
            "episode_links", link.id,
            self._corr_enc_row(episode_link_to_row(link)),
        )

    def find_episode_link(
        self, episode_id: str, external_type: str, external_id: str,
    ) -> Optional[EpisodeLink]:
        row = self._j_fetchone(
            "SELECT * FROM episode_links WHERE episode_id = ? AND "
            "external_type = ? AND external_id = ?",
            (episode_id, external_type, external_id),
        )
        return row_to_episode_link(row, decrypt=self._corr_dec) if row else None

    def list_episode_links(self, episode_id: str) -> list[EpisodeLink]:
        rows = self._j_fetchall(
            "SELECT * FROM episode_links WHERE episode_id = ? ORDER BY id",
            (episode_id,),
        )
        return [row_to_episode_link(r, decrypt=self._corr_dec) for r in rows]

    # -- episode phases ----------------------------------------------------

    def insert_episode_phase(self, phase: EpisodePhase) -> str:
        self._c_insert(
            "episode_phases", self._corr_enc_row(episode_phase_to_row(phase)),
        )
        return phase.id

    def update_episode_phase(self, phase: EpisodePhase) -> None:
        self._c_update(
            "episode_phases", phase.id,
            self._corr_enc_row(episode_phase_to_row(phase)),
        )

    def get_episode_phase(self, phase_id: str) -> Optional[EpisodePhase]:
        row = self._j_fetchone(
            "SELECT * FROM episode_phases WHERE id = ?", (phase_id,),
        )
        return row_to_episode_phase(row, decrypt=self._corr_dec) if row else None

    def list_episode_phases(self, episode_id: str) -> list[EpisodePhase]:
        rows = self._j_fetchall(
            "SELECT * FROM episode_phases WHERE episode_id = ? "
            "ORDER BY ordinal ASC, id ASC",
            (episode_id,),
        )
        return [row_to_episode_phase(r, decrypt=self._corr_dec) for r in rows]

    def delete_episode_phase(self, phase_id: str) -> None:
        self._j_exec("DELETE FROM episode_phases WHERE id = ?", (phase_id,))
        self._j_commit()

    # -- episode edges -----------------------------------------------------

    def insert_episode_edge(self, edge: EpisodeEdge) -> str:
        self._c_insert(
            "episode_edges", self._corr_enc_row(episode_edge_to_row(edge)),
        )
        return edge.id

    def update_episode_edge(self, edge: EpisodeEdge) -> None:
        self._c_update(
            "episode_edges", edge.id,
            self._corr_enc_row(episode_edge_to_row(edge)),
        )

    def get_episode_edge(self, edge_id: str) -> Optional[EpisodeEdge]:
        row = self._j_fetchone(
            "SELECT * FROM episode_edges WHERE id = ?", (edge_id,),
        )
        return row_to_episode_edge(row, decrypt=self._corr_dec) if row else None

    def list_episode_edges(self, episode_id: str) -> list[EpisodeEdge]:
        rows = self._j_fetchall(
            "SELECT * FROM episode_edges WHERE episode_id = ? ORDER BY id",
            (episode_id,),
        )
        return [row_to_episode_edge(r, decrypt=self._corr_dec) for r in rows]

    def delete_episode_edge(self, edge_id: str) -> None:
        self._j_exec("DELETE FROM episode_edges WHERE id = ?", (edge_id,))
        self._j_commit()

    # -- incremental correlation dirty index -------------------------------

    def mark_correlation_dirty(
        self, connector_record_id: str, *, vault_id: str = "", reason: str = "",
    ) -> None:
        from twin.clock import now_iso as _now
        if not connector_record_id:
            return
        existing = self._j_fetchone(
            "SELECT connector_record_id FROM correlation_dirty "
            "WHERE connector_record_id = ?",
            (connector_record_id,),
        )
        if existing:
            self._j_exec(
                "UPDATE correlation_dirty SET vault_id = ?, reason = ?, "
                "marked_at = ? WHERE connector_record_id = ?",
                (vault_id or "", reason or "", _now(), connector_record_id),
            )
            self._j_commit()
            return
        self._c_insert("correlation_dirty", {
            "connector_record_id": connector_record_id,
            "vault_id": vault_id or "",
            "reason": reason or "",
            "marked_at": _now(),
        })

    def list_correlation_dirty(
        self, *, vault_id: Optional[str] = None, limit: int = 5000,
    ) -> list[dict[str, Any]]:
        if vault_id:
            rows = self._j_fetchall(
                "SELECT connector_record_id, vault_id, reason, marked_at "
                "FROM correlation_dirty WHERE vault_id = ? "
                "ORDER BY marked_at ASC LIMIT ?",
                (vault_id, limit),
            )
        else:
            rows = self._j_fetchall(
                "SELECT connector_record_id, vault_id, reason, marked_at "
                "FROM correlation_dirty ORDER BY marked_at ASC LIMIT ?",
                (limit,),
            )
        out: list[dict[str, Any]] = []
        for r in rows:
            if hasattr(r, "keys"):
                out.append({
                    "connector_record_id": r["connector_record_id"],
                    "vault_id": r["vault_id"],
                    "reason": r["reason"],
                    "marked_at": r["marked_at"],
                })
            else:
                out.append({
                    "connector_record_id": r[0],
                    "vault_id": r[1],
                    "reason": r[2],
                    "marked_at": r[3],
                })
        return out

    def clear_correlation_dirty(self, connector_record_ids: list[str]) -> None:
        for rid in connector_record_ids:
            self._j_exec(
                "DELETE FROM correlation_dirty WHERE connector_record_id = ?",
                (rid,),
            )
        self._j_commit()
