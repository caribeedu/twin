"""Runtime configuration.

Layered architecture (v0.2):

    External World
        ↓  twin.sensory      (sensors → normalized percepts)
        ↓  twin.cognition    (extraction, dedupe, recall, attention)
        ↕  twin.memory       (stores, embeddings, search)
        ↕  twin.judgment     (PII, domain firewall, judgment profile)
        ↑  twin.interfaces   (CLI, HTTP API, MCP)

Config files live under a single home directory (default ``~/.twin`` or
``$TWIN_HOME``). The database can be SQLite (zero-config dev/tests) or
PostgreSQL + pgvector (primary, scalable backend) — selected by
``TWIN_DB_URL``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_HOME = Path(os.environ.get("TWIN_HOME", "~/.twin")).expanduser()

# Domains shipped in the MVP. The firewall also accepts the future ones so
# nothing breaks when they start showing up in data.
MVP_DOMAINS = ["work", "technical", "personal_preferences", "assistant_preferences"]
ALL_DOMAINS = MVP_DOMAINS + [
    "personal", "relationship", "family", "health",
    "finance", "social", "legal", "emotional", "general",
]

# Target pseudo-domain used when observation cannot classify the current
# context with enough confidence. It is deliberately NOT a memory domain:
# the firewall treats it as default-deny, so an ambiguous task never
# receives context it was not entitled to. The safe default is the most
# restrictive one, not the most frequent one.
UNCLASSIFIED_DOMAIN = "unclassified"

SENSITIVITY_ORDER = ["public", "internal", "private", "restricted"]


@dataclass
class Config:
    home: Path = field(default_factory=lambda: DEFAULT_HOME)

    # -- storage ---------------------------------------------------------
    # postgresql://user:pass@host:port/db  → Postgres + pgvector (primary)
    # sqlite:///path/to/twin.db            → SQLite (dev / tests / fallback)
    db_url: str = os.environ.get("TWIN_DB_URL", "")

    # -- local models (Ollama) ---------------------------------------------
    ollama_url: str = os.environ.get("TWIN_OLLAMA_URL", "http://127.0.0.1:11434")
    ollama_model: str = os.environ.get("TWIN_OLLAMA_MODEL", "qwen3:8b")
    ollama_embed_model: str = os.environ.get("TWIN_OLLAMA_EMBED_MODEL", "nomic-embed-text")

    # -- cognition ---------------------------------------------------------
    # auto → ollama (local, if reachable) → heuristic (rule-based, offline)
    extractor: str = os.environ.get("TWIN_EXTRACTOR", "auto")
    # Memories with confidence below this are always queued for review.
    review_confidence_threshold: float = 0.75

    # -- embeddings ---------------------------------------------------------
    # auto → ollama (if reachable) → hash; or force: hash | ollama
    embedder: str = os.environ.get("TWIN_EMBEDDER", "auto")
    embedding_dim: int = int(os.environ.get("TWIN_EMBEDDING_DIM", "512"))

    # -- privacy -------------------------------------------------------------
    # when set, percept content + evidence quotes are encrypted at rest
    # (requires: pip install "twin[crypto]")
    encryption_key: str = os.environ.get("TWIN_ENCRYPTION_KEY", "")
    # sources with trust below this always send their memories to review
    low_trust_threshold: float = 0.65

    @property
    def resolved_db_url(self) -> str:
        return self.db_url or f"sqlite:///{self.home / 'twin.db'}"

    @property
    def policies_path(self) -> Path:
        return self.home / "policies.yaml"

    @property
    def judgment_path(self) -> Path:
        return self.home / "judgment.yaml"

    def ensure_home(self) -> None:
        self.home.mkdir(parents=True, exist_ok=True)
        pkg_defaults = Path(__file__).parent / "defaults"
        if not self.policies_path.exists():
            self.policies_path.write_text(
                (pkg_defaults / "policies.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )
        if not self.judgment_path.exists():
            self.judgment_path.write_text(
                (pkg_defaults / "judgment.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )


def load_config(home: str | os.PathLike | None = None) -> Config:
    cfg = Config()
    if home is not None:
        cfg.home = Path(home).expanduser()
        # an explicit home implies its own sqlite db unless TWIN_DB_URL is set
        if not os.environ.get("TWIN_DB_URL"):
            cfg.db_url = ""
    return cfg
