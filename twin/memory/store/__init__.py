"""Store factory — picks the backend from the database URL."""

from __future__ import annotations

from typing import Optional

from ..crypto import ContentCodec
from .base import MemoryStore


def create_store(url: str, codec: Optional[ContentCodec] = None) -> MemoryStore:
    if url.startswith(("postgres://", "postgresql://")):
        from .postgres import PostgresStore

        return PostgresStore(url, codec=codec)
    if url.startswith("sqlite:///"):
        from .sqlite import SqliteStore

        return SqliteStore(url[len("sqlite:///"):], codec=codec)
    if url == "sqlite://:memory:" or url == ":memory:":
        from .sqlite import SqliteStore

        return SqliteStore(":memory:", codec=codec)
    raise ValueError(f"Unsupported TWIN_DB_URL: {url!r}")


__all__ = ["MemoryStore", "create_store"]
