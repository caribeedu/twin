"""FolderConnector — local/shared watched folders (v0.6 Phase 6).

Streams (explicit root allowlist):

    folder:{root_id}

Each sync performs a **full scan** of the root (not page-budgeted), emits
``document_manifest`` + ``document_revision_chunk`` records for new/changed
files, and tombstones for removals / chunk shrinks. Checkpoint
``known_files`` advances only after batch commit.

Document identity is **path-stable**, not rename-stable.

Cloud providers can share ``documents.DocumentRecord`` later.
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
from .scanner import (
    DEFAULT_MAX_KNOWN_FILES,
    FolderScanner,
    validate_roots,
)

STREAM_PREFIX = "folder"


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
        self.follow_symlinks = bool(cfg.get("follow_symlinks", False))
        self.allow_overlapping_roots = bool(
            cfg.get("allow_overlapping_roots", False),
        )
        self.max_known_files = int(
            cfg.get("max_known_files") or DEFAULT_MAX_KNOWN_FILES,
        )
        self._scanner: Optional[FolderScanner] = None
        self._store = None
        self._account_key = cfg.get("account_key") or account.external_account_id or "local"
        if self.roots:
            validate_roots(
                self.roots,
                allow_overlapping_roots=self.allow_overlapping_roots,
            )

    @property
    def scanner(self) -> FolderScanner:
        if self._scanner is None:
            self._scanner = FolderScanner(
                self.roots,
                include_globs=self.include_globs or None,
                exclude_globs=self.exclude_globs or None,
                max_file_bytes=self.max_file_bytes,
                follow_symlinks=self.follow_symlinks,
                max_known_files=self.max_known_files,
                allow_overlapping_roots=self.allow_overlapping_roots,
                validate=False,  # already validated in __init__
            )
        return self._scanner

    @staticmethod
    def adapter_manifest() -> AdapterManifest:
        return AdapterManifest(
            connector_type="folder",
            adapter_version="1.1",
            schema_version=1,
            auth_mode="none",
            affordances={
                # Content-hash skips unchanged files; each sync still walks
                # the full tree (no durable page cursor / continuation yet).
                "incremental_sync": True,
                "full_scan": True,
                "webhooks": False,
                "deletions": True,
                "attachments": False,
                "threads": False,
            },
            supported_external_types=[
                "document_manifest",
                "document_revision_chunk",
                "document_revision",
            ],
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
        try:
            validate_roots(
                self.roots,
                allow_overlapping_roots=self.allow_overlapping_roots,
            )
        except ConnectorError as exc:
            return ConnectorHealth(
                status=HealthStatus.failed,
                detail=str(exc),
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
        detail = (
            f"{len(roots)} local root(s) readable; full-scan watch-folder mode; "
            f"follow_symlinks={self.follow_symlinks}; "
            f"max_known_files={self.max_known_files}"
        )
        return ConnectorHealth(status=HealthStatus.healthy, detail=detail)

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
        validate_roots(
            self.roots,
            allow_overlapping_roots=self.allow_overlapping_roots,
        )
        root_id = self._parse_stream(stream)
        return SyncPlan(
            stream=stream,
            cursor_before=dict(checkpoint.cursor) if checkpoint else {},
            lookback_seconds=0,
            metadata={"root_id": root_id, "scan_mode": "full_scan"},
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

    def _previous_document_state(self, doc_id: str) -> dict[str, Any]:
        if self._store is None:
            return {}
        manifests = self._store.list_connector_records_for_object(
            self.instance.id, "document_manifest", f"{doc_id}:manifest",
        )
        live = [m for m in manifests if not m.deleted]
        chunk_count = 0
        if live:
            chunk_count = int(
                (live[-1].source_metadata or {}).get("chunk_count") or 0
            )
        return {"chunk_count": chunk_count}

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
        doc_id = str(obj.get("external_id") or raw_item.external_id)
        return records_from_document(
            connector_id=raw_item.connector_id,
            account_id=raw_item.source_account_id,
            account_key=str(account_key),
            document=obj,
            previous=self._previous_document_state(doc_id),
        )

    def acknowledge(self, plan: SyncPlan, page: FetchPage) -> dict[str, Any]:
        return page.cursor_after or dict(plan.cursor_before or {})
