"""Runtime configuration.

Layered architecture:

 External World
 ↓ twin.sense.sensory (sensors → normalized percepts)
 ↓ twin.cognition (extraction, dedupe, recall, attention)
 ↕ twin.store (stores, embeddings, search)
 ↕ twin.judgment (PII, domain firewall, judgment profile)
 ↑ twin.interfaces (CLI, HTTP API, MCP)

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

# Domains shipped in the initial concept. The firewall also accepts the future ones so
# nothing breaks when they start showing up in data.
BASE_DOMAINS = ["work", "technical", "personal_preferences", "assistant_preferences"]
ALL_DOMAINS = BASE_DOMAINS + [
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

# Chat / embed providers. Local Ollama is the encouraged default; users may
# opt into Anthropic, Gemini, OpenAI, or any OpenAI-compatible gateway.
LLM_PROVIDERS = (
    "ollama", "openai", "openai_compatible", "azure_openai",
    "anthropic", "claude", "gemini", "google",
    "groq", "together", "fireworks", "openrouter", "deepseek", "mistral", "xai",
    "lmstudio", "vllm",
)
EMBED_KINDS = ("auto", "ollama", "hash", "openai_compatible", "openai", "gemini")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default)


@dataclass
class Config:
    home: Path = field(default_factory=lambda: DEFAULT_HOME)

    # -- storage ---------------------------------------------------------
    # Environment is read at construction (not import) so a test or caller
    # that sets TWIN_* before building a Config actually takes effect.
    # postgresql://user:pass@host:port/db  → Postgres + pgvector (primary)
    # sqlite:///path/to/twin.db            → SQLite (dev / tests / fallback)
    db_url: str = field(default_factory=lambda: _env("TWIN_DB_URL", ""))

    # -- local models (Ollama) — kept as primary knobs for backward compat --
    ollama_url: str = field(
        default_factory=lambda: _env("TWIN_OLLAMA_URL", "http://127.0.0.1:11434"))
    ollama_model: str = field(
        default_factory=lambda: _env("TWIN_OLLAMA_MODEL", "qwen3.6:latest"))
    ollama_embed_model: str = field(
        default_factory=lambda: _env("TWIN_OLLAMA_EMBED_MODEL", "nomic-embed-text-v2-moe"))

    # -- pluggable LLM (interpreter + deep observer) -----------------------
    # ollama (default) | anthropic | gemini | openai | groq | openrouter | …
    llm_provider: str = field(
        default_factory=lambda: _env("TWIN_LLM_PROVIDER", "ollama").lower())
    # When set, overrides provider-specific base URL.
    llm_base_url: str = field(default_factory=lambda: _env("TWIN_LLM_BASE_URL", ""))
    llm_model: str = field(default_factory=lambda: _env("TWIN_LLM_MODEL", ""))
    llm_api_key: str = field(default_factory=lambda: _env("TWIN_LLM_API_KEY", ""))

    # -- cognition ---------------------------------------------------------
    # auto/ollama → cognitive interpreter (defer when unavailable);
    # heuristic → explicit offline detection mode.
    # ``auto`` follows llm_provider reachability.
    extractor: str = field(default_factory=lambda: _env("TWIN_EXTRACTOR", "auto"))
    # Memories with confidence below this are always queued for review.
    review_confidence_threshold: float = 0.75

    # -- embeddings ---------------------------------------------------------
    # auto → prefer configured provider if reachable → hash
    # force: hash | ollama | openai_compatible
    embedder: str = field(default_factory=lambda: _env("TWIN_EMBEDDER", "auto"))
    embed_base_url: str = field(default_factory=lambda: _env("TWIN_EMBED_BASE_URL", ""))
    embed_model: str = field(default_factory=lambda: _env("TWIN_EMBED_MODEL", ""))
    embed_api_key: str = field(
        default_factory=lambda: _env("TWIN_EMBED_API_KEY", "")
        or _env("TWIN_LLM_API_KEY", "")
        or _env("OPENAI_API_KEY", ""))
    embedding_dim: int = field(
        default_factory=lambda: int(_env("TWIN_EMBEDDING_DIM", "512")))

    # -- privacy -------------------------------------------------------------
    # when set, percept content + evidence quotes are encrypted at rest
    # (requires: pip install "twin-cognition[crypto]")
    encryption_key: str = field(default_factory=lambda: _env("TWIN_ENCRYPTION_KEY", ""))
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

    @property
    def calibration_path(self) -> Path:
        return self.home / "source_calibration.yaml"

    @property
    def normalized_llm_provider(self) -> str:
        from .llm import normalize_provider
        return normalize_provider(self.llm_provider)

    @property
    def llm_provider_kind(self) -> str:
        from .llm import provider_kind
        return provider_kind(self.llm_provider)

    @property
    def resolved_llm_base_url(self) -> str:
        if self.llm_base_url.strip():
            return self.llm_base_url.rstrip("/")
        from .llm import PROVIDER_PRESETS, normalize_provider
        preset = PROVIDER_PRESETS.get(normalize_provider(self.llm_provider), {})
        kind = preset.get("kind", "ollama")
        # Ollama's live URL is TWIN_OLLAMA_URL — never prefer the preset
        # localhost default over an explicit local server (e.g. WSL → Windows host).
        if kind == "ollama":
            return self.ollama_url.rstrip("/")
        base = (preset.get("base") or "").rstrip("/")
        if base:
            return base
        return self.ollama_url.rstrip("/")

    @property
    def resolved_llm_model(self) -> str:
        if self.llm_model.strip():
            return self.llm_model.strip()
        from .llm import PROVIDER_PRESETS, normalize_provider
        preset = PROVIDER_PRESETS.get(normalize_provider(self.llm_provider), {})
        if preset.get("kind") == "ollama":
            return self.ollama_model
        return (preset.get("default_model") or self.ollama_model).strip()

    @property
    def resolved_llm_api_key(self) -> str:
        from .llm import resolve_api_key
        return resolve_api_key(self)

    @property
    def resolved_embed_base_url(self) -> str:
        if self.embed_base_url.strip():
            return self.embed_base_url.rstrip("/")
        kind = self.embedder.strip().lower().replace("-", "_")
        llm_kind = self.llm_provider_kind
        if kind in ("openai", "openai_compatible") or (
            kind == "auto" and llm_kind == "openai_compatible"
        ):
            if llm_kind == "openai_compatible":
                return self.resolved_llm_base_url
            return "https://api.openai.com/v1"
        if kind == "gemini" or (kind == "auto" and llm_kind == "gemini"):
            return "https://generativelanguage.googleapis.com"
        return self.ollama_url.rstrip("/")

    @property
    def resolved_embed_model(self) -> str:
        if self.embed_model.strip():
            return self.embed_model.strip()
        kind = self.embedder.strip().lower().replace("-", "_")
        if kind == "gemini" or (
            kind == "auto" and self.llm_provider_kind == "gemini"
        ):
            return "text-embedding-004"
        if kind in ("openai", "openai_compatible") or (
            kind == "auto" and self.llm_provider_kind == "openai_compatible"
        ):
            return "text-embedding-3-small"
        return self.ollama_embed_model.strip()

    @property
    def resolved_embed_api_key(self) -> str:
        return self.embed_api_key or self.resolved_llm_api_key

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
        if not self.calibration_path.exists():
            self.calibration_path.write_text(
                (pkg_defaults / "source_calibration.yaml").read_text(encoding="utf-8"),
                encoding="utf-8",
            )


def load_config(home: str | os.PathLike | None = None) -> Config:
    home_path = Path(home).expanduser() if home is not None else DEFAULT_HOME
    # Local dotenv written by `twin init` / setup wizard. Does not override
    # variables already present in the process environment.
    try:
        from .interfaces.ux import apply_env_file
        apply_env_file(home_path / "env")
    except Exception:
        pass
    cfg = Config()
    if home is not None:
        cfg.home = home_path
        # an explicit home implies its own sqlite db unless TWIN_DB_URL is set
        if not os.environ.get("TWIN_DB_URL"):
            cfg.db_url = ""
    return cfg
