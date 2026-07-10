"""Store factory — picks the backend from the database URL."""

from __future__ import annotations

from .base import MemoryStore


def create_store(url: str) -> MemoryStore:
    if url.startswith(("postgres://", "postgresql://")):
        from .postgres import PostgresStore

        return PostgresStore(url)
    if url.startswith("sqlite:///"):
        from .sqlite import SqliteStore

        return SqliteStore(url[len("sqlite:///"):])
    if url == "sqlite://:memory:" or url == ":memory:":
        from .sqlite import SqliteStore

        return SqliteStore(":memory:")
    raise ValueError(f"Unsupported TWIN_DB_URL: {url!r}")


__all__ = ["MemoryStore", "create_store"]
