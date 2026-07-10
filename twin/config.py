"""Runtime configuration.

Everything lives under a single data directory (default ``~/.twin`` or the
``TWIN_HOME`` env var), so the whole brain is one folder you can back up,
sync or delete:

    <home>/twin.db            SQLite database (graph + vectors + FTS)
    <home>/policies.yaml      Domain Firewall rules
    <home>/judgment.yaml      Judgment profile
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

SENSITIVITY_ORDER = ["public", "internal", "private", "restricted"]


@dataclass
class Config:
    home: Path = field(default_factory=lambda: DEFAULT_HOME)
    # "auto" uses the LLM extractor when an Anthropic credential is available,
    # otherwise falls back to the heuristic extractor.
    extractor: str = os.environ.get("TWIN_EXTRACTOR", "auto")
    extraction_model: str = os.environ.get("TWIN_EXTRACTION_MODEL", "claude-opus-4-8")
    # "hash" is the zero-dependency local embedder; "sentence-transformers"
    # is used when the package is installed and TWIN_EMBEDDER selects it.
    embedder: str = os.environ.get("TWIN_EMBEDDER", "hash")
    embedding_dim: int = int(os.environ.get("TWIN_EMBEDDING_DIM", "512"))
    # Memories with confidence below this are always queued for review.
    review_confidence_threshold: float = 0.75
    # Cloud extraction only ever sees PII-masked text.
    mask_pii_before_cloud: bool = True

    @property
    def db_path(self) -> Path:
        return self.home / "twin.db"

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
    return cfg
