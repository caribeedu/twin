"""The adapter contract: ``ProfessionalConnector``.

The framework owns credentials, accounts, checkpointing, retries, idempotency,
audit, health, deletion, backfill, quarantine and metrics. An adapter only
implements source-specific fetch + normalize.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable

from .models import (
    ConnectorCheckpoint,
    ConnectorInstance,
    ConnectorRecord,
    FailureClass,
    HealthStatus,
    RawConnectorItem,
    SourceAccount,
)


class ConnectorError(Exception):
    """Structured connector failure. Never a bare string."""

    def __init__(
        self,
        message: str,
        *,
        failure_class: FailureClass = FailureClass.provider_error,
        retryable: bool = False,
        retry_after: Optional[int] = None,
        human_action_required: bool = False,
        external_id: str = "",
        external_type: str = "",
    ) -> None:
        super().__init__(message)
        self.failure_class = failure_class
        self.retryable = retryable
        self.retry_after = retry_after
        self.human_action_required = human_action_required
        self.external_id = external_id
        self.external_type = external_type


@dataclass
class AdapterManifest:
    connector_type: str
    adapter_version: str = "1.0"
    schema_version: int = 1
    affordances: dict[str, bool] = field(default_factory=dict)
    supported_external_types: list[str] = field(default_factory=list)
    streams: list[str] = field(default_factory=list)
    default_scopes: list[str] = field(default_factory=list)


@dataclass
class ConnectorHealth:
    status: HealthStatus = HealthStatus.healthy
    detail: str = ""
    scopes: list[str] = field(default_factory=list)


@dataclass
class SyncPlan:
    stream: str
    cursor_before: dict[str, Any] = field(default_factory=dict)
    lookback_seconds: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class RawFetchItem:
    """One raw object as returned by the source, before persistence."""
    external_type: str
    external_id: str
    external_revision: str = "0"
    payload: dict[str, Any] = field(default_factory=dict)
    occurred_at: Optional[str] = None
    deleted: bool = False


@dataclass
class FetchPage:
    raw_items: list[RawFetchItem] = field(default_factory=list)
    cursor_after: dict[str, Any] = field(default_factory=dict)
    done: bool = True


@runtime_checkable
class ProfessionalConnector(Protocol):
    connector_type: str

    def __init__(
        self,
        instance: ConnectorInstance,
        account: SourceAccount,
        secret: Optional[str],
    ) -> None: ...

    @staticmethod
    def adapter_manifest() -> AdapterManifest: ...

    def discover_accounts(self) -> list[SourceAccount]: ...

    def validate_credentials(self) -> ConnectorHealth: ...

    def plan_sync(
        self,
        account: SourceAccount,
        checkpoint: Optional[ConnectorCheckpoint],
        *,
        stream: str,
    ) -> SyncPlan: ...

    def fetch_batch(self, plan: SyncPlan, cursor: Optional[dict[str, Any]]) -> FetchPage: ...

    def normalize(self, raw_item: RawConnectorItem) -> list[ConnectorRecord]: ...

    def acknowledge(self, plan: SyncPlan, page: FetchPage) -> dict[str, Any]: ...
