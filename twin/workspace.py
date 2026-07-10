"""Workspace: one object bundling config + db + embedder + firewall, shared
by the CLI, HTTP API and MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .config import Config, load_config
from .db import Database
from .embeddings import Embedder, get_embedder
from .firewall import Firewall


class Workspace:
    def __init__(self, home: Optional[str | Path] = None):
        self.cfg: Config = load_config(home)
        self.cfg.ensure_home()
        self.db = Database(self.cfg.db_path)
        self.embedder: Embedder = get_embedder(self.cfg.embedder, self.cfg.embedding_dim)

    @property
    def firewall(self) -> Firewall:
        # Reload per access so YAML edits apply without restarting servers.
        return Firewall(self.cfg.policies_path, self.db)

    def close(self) -> None:
        self.db.close()
