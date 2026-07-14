"""Adapter registry — maps ``connector_type`` to its ProfessionalConnector."""

from __future__ import annotations

from typing import Optional

from .models import ConnectorInstance, SourceAccount
from .protocol import AdapterManifest, ProfessionalConnector

_ADAPTERS: dict[str, type] = {}


def register_adapter(cls: type) -> type:
    """Class decorator: register an adapter by its ``connector_type``."""
    connector_type = getattr(cls, "connector_type", None)
    if not connector_type:
        raise ValueError(f"{cls.__name__} must define connector_type")
    _ADAPTERS[connector_type] = cls
    return cls


def get_adapter_class(connector_type: str) -> type:
    if connector_type not in _ADAPTERS:
        raise ValueError(f"no connector adapter registered for {connector_type!r}")
    return _ADAPTERS[connector_type]


def list_adapters() -> list[str]:
    return sorted(_ADAPTERS)


def get_manifest(connector_type: str) -> AdapterManifest:
    return get_adapter_class(connector_type).adapter_manifest()


def build_adapter(
    instance: ConnectorInstance,
    account: SourceAccount,
    secret: Optional[str],
) -> ProfessionalConnector:
    cls = get_adapter_class(instance.connector_type)
    return cls(instance, account, secret)
