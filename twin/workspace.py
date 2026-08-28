"""Workspace: wires the layers together — config + store + embedder +
firewall — shared by the CLI, HTTP API and MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .config import Config, load_config
from .privacy.firewall import Firewall
from .store.crypto import build_codec
from .store.embeddings import Embedder, get_embedder_for_config
from .store.store import TwinStore, create_store


class Workspace:
    def __init__(self, home: Optional[str | Path] = None):
        self.cfg: Config = load_config(home)
        self.cfg.ensure_home()
        codec = build_codec(self.cfg.encryption_key, self.cfg.home)
        self.store: TwinStore = create_store(self.cfg.resolved_db_url, codec=codec)
        self.embedder: Embedder = get_embedder_for_config(self.cfg)
        # Record LLM token/cost usage to the home ledger (idempotent per home).
        try:
            from .llm.usage import install_ledger_sink
            install_ledger_sink(self.cfg.home)
        except Exception:
            pass

    @property
    def firewall(self) -> Firewall:
        # Reload per access so YAML edits apply without restarting servers.
        return Firewall(self.cfg.policies_path, self.store)

    def ingest(self, paths: list[str | Path]) -> tuple[list[str], list[str]]:
        """Sense external signals and persist the resulting percepts.
        Returns (new_percept_ids, skipped)."""
        from .sense.sensory import sense_paths

        percepts, skipped = sense_paths(paths)
        new_ids: list[str] = []
        for percept in percepts:
            if self.store.insert_percept(percept) is None:
                skipped.append(f"{percept.content_refs[0].get('path', percept.id)} (duplicate)"
                               if percept.content_refs else f"{percept.id} (duplicate)")
            else:
                new_ids.append(percept.id)
        return new_ids, skipped

    def reindex(self) -> int:
        """Regenerate every memory embedding with the current embedder
        (run after switching TWIN_EMBEDDER / embedding model)."""
        count = 0
        for mem in self.store.list_claims(limit=1_000_000):
            vector = self.embedder.embed(f"{mem.title}\n{mem.summary}")
            self.store.store_embedding(mem.id, "claim", self.embedder.name, vector)
            count += 1
        return count

    def close(self) -> None:
        self.store.close()
