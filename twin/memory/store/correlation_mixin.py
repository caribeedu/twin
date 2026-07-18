"""Cross-source correlation store mixin (v0.6 Phase 7)."""

from __future__ import annotations

from typing import Any, Optional

from twin.cognition.correlation.models import (
    EpisodeLink,
    ExternalIdentity,
    IdentityLink,
    ProjectLink,
    WorkEpisode,
)
from twin.cognition.correlation.persistence import (
    episode_link_to_row,
    episode_to_row,
    identity_link_to_row,
    identity_to_row,
    project_link_to_row,
    row_to_episode,
    row_to_episode_link,
    row_to_identity,
    row_to_identity_link,
    row_to_project_link,
)

CORRELATION_SCHEMA = """
CREATE TABLE IF NOT EXISTS external_identities (
    id TEXT PRIMARY KEY,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_account_id TEXT NOT NULL DEFAULT '',
    actor_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_extid_provider
    ON external_identities(provider, external_id);
CREATE INDEX IF NOT EXISTS idx_extid_actor ON external_identities(actor_id);

CREATE TABLE IF NOT EXISTS identity_links (
    id TEXT PRIMARY KEY,
    left_identity_id TEXT NOT NULL,
    right_identity_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'candidate',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_idlink_left ON identity_links(left_identity_id);
CREATE INDEX IF NOT EXISTS idx_idlink_right ON identity_links(right_identity_id);

CREATE TABLE IF NOT EXISTS project_links (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    external_type TEXT NOT NULL,
    external_id TEXT NOT NULL,
    source_account_id TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_projlink_ext
    ON project_links(external_type, external_id);

CREATE TABLE IF NOT EXISTS work_episodes (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'candidate',
    independence_group TEXT NOT NULL DEFAULT '',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episode_indep ON work_episodes(independence_group);
CREATE INDEX IF NOT EXISTS idx_episode_project ON work_episodes(project_id);

CREATE TABLE IF NOT EXISTS episode_links (
    id TEXT PRIMARY KEY,
    episode_id TEXT NOT NULL,
    external_type TEXT NOT NULL DEFAULT '',
    external_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL DEFAULT 'soft',
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_eplink_episode ON episode_links(episode_id);
CREATE INDEX IF NOT EXISTS idx_eplink_ext
    ON episode_links(external_type, external_id);
"""


class CorrelationStoreMixin:
    """Duck-typed persistence for Phase 7 correlation objects."""

    def _corr_dec(self, payload: Any) -> Any:
        # Payloads are not secret cognitive content; still go through codec
        # for consistency with other mixins when encryption is on.
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
        self, *, provider: Optional[str] = None,
    ) -> list[ExternalIdentity]:
        if provider:
            rows = self._j_fetchall(
                "SELECT * FROM external_identities WHERE provider = ? ORDER BY id",
                (provider,),
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

    def list_identity_links(self) -> list[IdentityLink]:
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
        source_account_id: Optional[str] = None,
    ) -> Optional[ProjectLink]:
        if source_account_id:
            row = self._j_fetchone(
                "SELECT * FROM project_links WHERE external_type = ? AND "
                "external_id = ? AND source_account_id = ?",
                (external_type, external_id, source_account_id),
            )
        else:
            row = self._j_fetchone(
                "SELECT * FROM project_links WHERE external_type = ? AND "
                "external_id = ? ORDER BY id LIMIT 1",
                (external_type, external_id),
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

    def find_work_episode_by_lineage(
        self, lineage_root: str,
    ) -> Optional[WorkEpisode]:
        key = f"lineage:{lineage_root}" if not lineage_root.startswith("lineage:") else lineage_root
        row = self._j_fetchone(
            "SELECT * FROM work_episodes WHERE independence_group = ? "
            "ORDER BY id LIMIT 1",
            (key if key.startswith("lineage:") else f"lineage:{lineage_root}",),
        )
        if row:
            return row_to_episode(row, decrypt=self._corr_dec)
        # Also match bare lineage stored without prefix
        row = self._j_fetchone(
            "SELECT * FROM work_episodes WHERE independence_group = ? "
            "ORDER BY id LIMIT 1",
            (lineage_root,),
        )
        return row_to_episode(row, decrypt=self._corr_dec) if row else None

    def list_work_episodes(
        self, *, project_id: Optional[str] = None, limit: int = 200,
    ) -> list[WorkEpisode]:
        if project_id:
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
