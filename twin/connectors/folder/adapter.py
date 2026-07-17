"""FolderConnector — local/shared watched folders (v0.6 Phase 6).

Streams (explicit root allowlist):

    folder:{root_id}

Each sync scans the root, emits document revisions for new/changed files,
and tombstones for removals. Checkpoint ``known_files`` advances only after
batch commit. Cloud providers can share ``documents.DocumentRecord`` later.
"""

from __future__ import annotations

from typing import Any, Optional

from ..documents.normalize import records_from_document, revision_for_document
from ..models import (
    ConnectorCheckpoint,
    ConnectorInstance,
    ConnectorRecord,
    FailureClass,
    HealthStatus,
    RawConnectorItem,
    SourceAccount,
)
from ..protocol import (
    AdapterManifest,
    ConnectorError,
    ConnectorHealth,
    FetchPage,
    RawFetchItem,
    SyncPlan,
)
from ..registry import register_adapter
from .scanner import FolderScanner

STREAM_PREFIX = "folder"
DEFAULT_MAX_PAGES = 1  # one scan = one batch per root


@register_adapter
class FolderConnector:
    connector_type = "folder"

    def __init__(
        self,
        instance: ConnectorInstance,
        account: SourceAccount,
        secret: Optional[str],
    ) -> None:
        self.instance = instance
        self.account = account
        self.secret = secret  # unused for local roots; kept for protocol symmetry
        cfg = instance.configuration or {}
        self.roots: list[dict[str, Any]] = list(cfg.get("roots") or [])
        self.include_globs = list(cfg.get("include_globs") or [])
        self.exclude_globs = list(cfg.get("exclude_globs") or [])
        self.max_file_bytes = int(cfg.get("max_file_bytes") or 2_000_000)
        self.max_pages = int(cfg.get("max_pages_per_stream", DEFAULT_MAX_PAGES))
        self._scanner: Optional[FolderScanner] = None
        self._store = None
        self._account_key = cfg.get("account_key") or account.external_account_id or "local"

    @property
    def scanner(self) -> FolderScanner:
        if self._scanner is None:
            self._scanner = FolderScanner(
                self.roots,
                include_globs=self.include_globs or None,
                exclude_globs=self.exclude_globs or None,
                max_file_bytes=self.max_file_bytes,
            )
        return self._scanner

    @staticmethod
    def adapter_manifest() -> AdapterManifest:
        return AdapterManifest(
            connector_type="folder",
            adapter_version="1.0",
            schema_version=1,
            auth_mode="none",
            affordances={
                "incremental_sync": True,
                "webhooks": False,
                "deletions": True,
                "attachments": False,
                "threads": False,
            },
            supported_external_types=["document_revision"],
            streams=[],
            dynamic_streams=True,
            default_scopes=["filesystem:read"],
        )

    def discover_accounts(self) -> list[SourceAccount]:
        return [self.account]

    def list_roots(self) -> list[dict[str, Any]]:
        return self.scanner.list_roots()

    def validate_credentials(self) -> ConnectorHealth:
        if not self.roots:
            return ConnectorHealth(
                status=HealthStatus.healthy,
                detail="no roots configured yet; awaiting_configuration on sync",
            )
        roots = self.scanner.list_roots()
        missing = [r["id"] for r in roots if not r.get("exists")]
        unreadable = [r["id"] for r in roots if r.get("exists") and not r.get("readable")]
        if missing:
            return ConnectorHealth(
                status=HealthStatus.degraded,
                detail=f"roots missing: {', '.join(missing)}",
            )
        if unreadable:
            return ConnectorHealth(
                status=HealthStatus.unauthorized,
                detail=f"roots not readable: {', '.join(unreadable)}",
            )
        return ConnectorHealth(
            status=HealthStatus.healthy,
            detail=f"{len(roots)} local root(s) readable; watch-folder mode",
        )

    def plan_streams(self, account: SourceAccount) -> list[str]:
        return [f"{STREAM_PREFIX}:{self.scanner._root_id(r)}" for r in self.roots]

    def plan_sync(
        self,
        account: SourceAccount,
        checkpoint: Optional[ConnectorCheckpoint],
        *,
        stream: str,
    ) -> SyncPlan:
        if not self.roots:
            raise ConnectorError(
                "no folder roots configured",
                failure_class=FailureClass.configuration,
                human_action_required=True,
            )
        root_id = self._parse_stream(stream)
        return SyncPlan(
            stream=stream,
            cursor_before=dict(checkpoint.cursor) if checkpoint else {},
            lookback_seconds=0,
            metadata={"root_id": root_id},
        )

    def _parse_stream(self, stream: str) -> str:
        parts = stream.split(":", 1)
        if len(parts) != 2 or parts[0] != STREAM_PREFIX or not parts[1]:
            raise ConnectorError(
                f"unknown folder stream layout: {stream!r}",
                failure_class=FailureClass.schema_change,
            )
        return parts[1]

    def fetch_batch(
        self, plan: SyncPlan, cursor: Optional[dict[str, Any]],
    ) -> FetchPage:
        root_id = plan.metadata["root_id"]
        base = dict(cursor or plan.cursor_before or {})
        docs, next_cursor, done = self.scanner.scan(root_id, cursor=base)
        items: list[RawFetchItem] = []
        for doc in docs:
            obj = doc.to_dict()
            # Absolute paths stay out of cognitive payload — keep root-relative.
            if isinstance(obj.get("raw_metadata"), dict):
                meta = dict(obj["raw_metadata"])
                meta.pop("absolute_path", None)
                obj["raw_metadata"] = meta
            items.append(RawFetchItem(
                external_type="document_revision",
                external_id=doc.external_id,
                external_revision=revision_for_document(obj),
                payload={
                    "provider": "folder",
                    "account_key": self._account_key,
                    "root_id": root_id,
                    "object": obj,
                },
                occurred_at=(doc.revision.modified_at if doc.revision else None),
                deleted=doc.deleted,
            ))
        return FetchPage(
            raw_items=items,
            cursor_after=next_cursor,
            done=done,
        )

    def normalize(self, raw_item: RawConnectorItem) -> list[ConnectorRecord]:
        payload = raw_item.payload or {}
        obj = payload.get("object")
        if not isinstance(obj, dict):
            raise ConnectorError(
                "folder raw item missing object envelope",
                failure_class=FailureClass.schema_change,
                external_id=raw_item.external_id,
                external_type=raw_item.external_type,
            )
        account_key = payload.get("account_key") or self._account_key or "local"
        return records_from_document(
            connector_id=raw_item.connector_id,
            account_id=raw_item.source_account_id,
            account_key=str(account_key),
            document=obj,
        )

    def acknowledge(self, plan: SyncPlan, page: FetchPage) -> dict[str, Any]:
        return page.cursor_after or dict(plan.cursor_before or {})
