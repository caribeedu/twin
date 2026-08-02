"""Operational ergonomics: twin doctor / twin setup.

``twin doctor`` verifies models, stores, pgvector, migrations, encryption
configuration, policies, judgment profile, embeddings and MCP client
configuration. ``twin setup`` bootstraps Ollama models, the Postgres
schema and MCP client configs.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import yaml

from ..config import Config

OK, WARN, FAIL = "ok", "warn", "fail"


@dataclass
class Check:
    name: str
    status: str
    detail: str = ""


def _mcp_config_paths() -> dict[str, Path]:
    home = Path.home()
    if platform.system() == "Darwin":
        desktop = home / "Library/Application Support/Claude/claude_desktop_config.json"
    elif platform.system() == "Windows":
        desktop = Path(os.environ.get("APPDATA", home)) / "Claude/claude_desktop_config.json"
    else:
        desktop = home / ".config/Claude/claude_desktop_config.json"
    return {
        "claude-desktop": desktop,
        "cursor": home / ".cursor/mcp.json",
        "claude-code": Path.cwd() / ".mcp.json",
    }


def _runtime_queue_checks(store) -> list[Check]:
    """Report runtime queue health without pretending a worker is up.

    No pidfile means we can't claim "process up"; instead we surface backlog so
    the operator knows whether ``twin runtime start`` needs to run. Pending or
    dead-lettered jobs degrade native SessionEnd consolidation + domain resolve.
    """
    checks: list[Check] = []
    try:
        depth = store.runtime_queue_depth()
    except Exception as exc:
        return [Check("runtime:queue", WARN, f"queue depth unavailable: {exc}")]

    pending = int(depth.get("pending", 0))
    failed = int(depth.get("failed", 0))
    dead = int(depth.get("dead_letter", 0))
    running = int(depth.get("running", 0))

    if pending:
        checks.append(Check(
            "runtime:queue", WARN,
            f"{pending} jobs pending"
            + (f", {running} running" if running else "")
            + " — run `twin runtime start`",
        ))
    else:
        checks.append(Check(
            "runtime:queue", OK,
            "no pending jobs" + (f" ({running} running)" if running else ""),
        ))

    if failed:
        checks.append(Check(
            "runtime:failed", WARN,
            f"{failed} jobs failed (retrying with backoff)",
        ))
    if dead:
        checks.append(Check(
            "runtime:dead_letter", FAIL,
            f"{dead} dead-letter jobs — inspect with `twin runtime jobs`",
        ))
    return checks


def doctor(cfg: Config) -> list[Check]:
    checks: list[Check] = []

    # optional dependencies
    for module, extra in (("fastapi", "api"), ("mcp", "mcp"),
                          ("psycopg", "postgres"), ("cryptography", "crypto")):
        try:
            __import__(module)
            checks.append(Check(f"dependency:{module}", OK))
        except ImportError:
            checks.append(Check(f"dependency:{module}", WARN,
                                f'not installed — pip install "twin-cognition[{extra}]"'))

    # store connectivity + backend capabilities (also runs migrations)
    url = cfg.resolved_db_url
    try:
        from ..memory.store import create_store

        store = create_store(url)
        backend = type(store).__name__
        if backend == "PostgresStore":
            detail = "pgvector active" if store.has_pgvector else \
                "pgvector missing — vector search degrades to client-side"
            checks.append(Check("store:postgres", OK if store.has_pgvector else WARN, detail))
        else:
            checks.append(Check("store:sqlite", WARN if url.startswith("postgres") else OK,
                                url))
        checks.append(Check("store:migrations", OK, "schema up to date"))
        pending = len([m for m in store.list_memories(status="candidate") if m.needs_review])
        if pending:
            checks.append(Check("review:queue", WARN, f"{pending} memories awaiting review"))
        else:
            checks.append(Check("review:queue", OK, "empty"))
        checks.extend(_runtime_queue_checks(store))
        store.close()
    except Exception as exc:
        checks.append(Check("store:connection", FAIL, f"{url} → {exc}"))

    # LLM + models (provider-aware)
    from ..cognition.llm import llm_available, provider_kind
    from ..memory.embeddings import get_embedder_for_config, ollama_reachable

    provider = cfg.normalized_llm_provider
    kind = provider_kind(provider)
    checks.append(Check("llm:provider", OK, f"{provider} ({kind})"))
    if kind == "ollama":
        if ollama_reachable(cfg.resolved_llm_base_url):
            try:
                import httpx

                tags = httpx.get(
                    f"{cfg.resolved_llm_base_url.rstrip('/')}/api/tags", timeout=5,
                ).json()
                available = {m["name"].split(":")[0] for m in tags.get("models", [])}
                for role, model in (
                    ("extraction", cfg.resolved_llm_model),
                    ("embeddings", cfg.resolved_embed_model),
                ):
                    base = model.split(":")[0]
                    if base in available:
                        checks.append(Check(f"ollama:{role}", OK, model))
                    else:
                        checks.append(Check(
                            f"ollama:{role}", WARN,
                            f"model {model} not pulled — twin setup ollama",
                        ))
            except Exception as exc:
                checks.append(Check("ollama:models", WARN, str(exc)))
        else:
            checks.append(Check(
                "ollama:server", WARN,
                f"{cfg.resolved_llm_base_url} unreachable — extraction defers; "
                "embeddings fall back to hash when embedder=auto",
            ))
    else:
        if llm_available(cfg):
            checks.append(Check(
                "llm:server", OK,
                f"{cfg.resolved_llm_base_url} · model={cfg.resolved_llm_model}",
            ))
        else:
            checks.append(Check(
                "llm:server", WARN,
                f"{cfg.resolved_llm_base_url} unreachable — check TWIN_LLM_BASE_URL / API key",
            ))
        if not cfg.resolved_llm_api_key:
            hint = {
                "anthropic": "set ANTHROPIC_API_KEY or TWIN_LLM_API_KEY",
                "gemini": "set GEMINI_API_KEY / GOOGLE_API_KEY or TWIN_LLM_API_KEY",
                "openai_compatible": "set TWIN_LLM_API_KEY (ok empty for some local servers)",
            }.get(kind, "set TWIN_LLM_API_KEY")
            checks.append(Check("llm:api_key", WARN, hint))

    # embedder resolution
    embedder = get_embedder_for_config(cfg)
    checks.append(Check("embedder", OK, embedder.name))

    # policies + judgment parse
    for label, path in (("policies", cfg.policies_path), ("judgment", cfg.judgment_path)):
        try:
            if path.exists():
                yaml.safe_load(path.read_text(encoding="utf-8"))
                checks.append(Check(f"config:{label}", OK, str(path)))
            else:
                checks.append(Check(f"config:{label}", WARN, f"{path} missing — twin init"))
        except yaml.YAMLError as exc:
            checks.append(Check(f"config:{label}", FAIL, f"invalid YAML: {exc}"))

    # encryption
    if cfg.encryption_key:
        try:
            from ..memory.crypto import build_codec

            build_codec(cfg.encryption_key, cfg.home)
            checks.append(Check("encryption", OK, "at-rest encryption active"))
        except RuntimeError as exc:
            checks.append(Check("encryption", FAIL, str(exc)))
    else:
        checks.append(Check("encryption", WARN, "TWIN_ENCRYPTION_KEY not set (optional)"))

    # MCP client configuration
    found_any = False
    for client, path in _mcp_config_paths().items():
        if path.exists() and '"twin"' in path.read_text(encoding="utf-8", errors="ignore"):
            checks.append(Check(f"mcp:{client}", OK, str(path)))
            found_any = True
    if not found_any:
        checks.append(Check("mcp:clients", WARN,
                            "no client configured — twin setup mcp <client>"))

    # connector schedule / credentials / instance health
    try:
        from ..connectors.ops import doctor_connector_checks
        from ..memory.store import create_store

        conn_store = create_store(cfg.resolved_db_url)
        try:
            for row in doctor_connector_checks(conn_store, cfg.home):
                status = row.get("status", WARN)
                if status not in (OK, WARN, FAIL):
                    status = WARN
                checks.append(Check(row["name"], status, row.get("detail", "")))
        finally:
            conn_store.close()
    except Exception as exc:
        checks.append(Check("connectors", WARN, f"connector checks skipped: {exc}"))

    return checks


def setup_ollama(cfg: Config) -> list[str]:
    """Pull the configured models (via the ollama CLI when available)."""
    lines: list[str] = []
    from ..memory.embeddings import ollama_reachable

    if not ollama_reachable(cfg.ollama_url):
        lines.append(f"Ollama unreachable at {cfg.ollama_url}.")
        lines.append("Start it with one of:")
        lines.append("  docker compose up -d ollama")
        lines.append("  ollama serve   (native install: https://ollama.com/download)")
        return lines
    for model in (cfg.ollama_model, cfg.ollama_embed_model):
        if shutil.which("ollama"):
            lines.append(f"pulling {model} …")
            proc = subprocess.run(["ollama", "pull", model], capture_output=True, text=True)
            lines.append(f"  {'done' if proc.returncode == 0 else proc.stderr.strip()}")
        else:
            lines.append(f"run: docker compose exec ollama ollama pull {model}")
    return lines


def setup_postgres(cfg: Config) -> list[str]:
    """Verify connectivity, create the extension/schema, or explain how."""
    url = cfg.resolved_db_url
    if not url.startswith(("postgres://", "postgresql://")):
        return [
            "TWIN_DB_URL does not point at Postgres.",
            "  docker compose up -d postgres",
            "  export TWIN_DB_URL=postgresql://twin:twin@localhost:5432/twin",
        ]
    try:
        from ..memory.store.postgres import PostgresStore

        store = PostgresStore(url)
        pg = "pgvector active" if store.has_pgvector else "pgvector MISSING"
        store.close()
        return [f"connected to {url}", f"schema created/verified — {pg}"]
    except Exception as exc:
        return [f"connection failed: {exc}",
                "  docker compose up -d postgres  (then retry)"]


def setup_mcp(cfg: Config, client: str) -> list[str]:
    """Write/merge the twin server entry into a client's MCP config.

    Provisions a ClientBinding + durable token and injects
    ``TWIN_MCP_CLIENT`` / ``TWIN_MCP_CLIENT_TOKEN`` into the host env block.
    The model never sees or passes these credentials.
    """
    from pathlib import Path

    from twin.interfaces.mcp_auth import (
        MCP_CLIENT_ENV,
        provision_mcp_client,
    )
    from twin.workspace import Workspace

    paths = _mcp_config_paths()
    if client not in paths:
        return [f"unknown client '{client}'. Options: {', '.join(paths)}"]
    path = paths[client]

    ws = Workspace(cfg.home)
    try:
        ident_env = provision_mcp_client(
            ws.store, Path(cfg.home), client,
            policies_path=cfg.policies_path,
        )
    finally:
        ws.close()

    entry: dict = {"command": shutil.which("twin") or "twin", "args": ["mcp"]}
    env: dict[str, str] = {}
    for key in (
        "TWIN_DB_URL",
        "TWIN_HOME",
        "TWIN_LLM_PROVIDER",
        "TWIN_LLM_BASE_URL",
        "TWIN_LLM_MODEL",
        "TWIN_LLM_API_KEY",
        "TWIN_OLLAMA_URL",
        "TWIN_OLLAMA_MODEL",
        "TWIN_OLLAMA_EMBED_MODEL",
        "TWIN_EMBEDDER",
        "TWIN_EMBED_BASE_URL",
        "TWIN_EMBED_MODEL",
        "TWIN_EMBED_API_KEY",
        "TWIN_EXTRACTOR",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "GEMINI_API_KEY",
        "GOOGLE_API_KEY",
        "GROQ_API_KEY",
        "OPENROUTER_API_KEY",
        "AZURE_OPENAI_API_KEY",
        "TOGETHER_API_KEY",
        "FIREWORKS_API_KEY",
        "DEEPSEEK_API_KEY",
        "MISTRAL_API_KEY",
        "XAI_API_KEY",
    ):
        if os.environ.get(key):
            env[key] = os.environ[key]
    # Prefer values from ~/.twin/env when process env lacks them
    try:
        from .ux import load_env_file, write_env_file
        for key, value in load_env_file(cfg.home / "env").items():
            env.setdefault(key, value)
        # Persist identity into ~/.twin/env for this machine's last setup.
        write_env_file(cfg.home / "env", ident_env)
    except Exception:
        pass
    env.update(ident_env)
    entry["env"] = env
    config: dict = {}
    if path.exists():
        try:
            config = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return [f"{path} exists but is not valid JSON — fix it manually"]
    config.setdefault("mcpServers", {})["twin"] = entry
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    lines = [
        f"wrote {path}",
        f"provisioned MCP identity {MCP_CLIENT_ENV}={client} "
        f"(token in env + ~/.twin/secrets/mcp/)",
    ]
    if client == "claude-desktop":
        lines.append("restart Claude Desktop to load the server")
    if client == "claude-code":
        lines.append("scope: project (.mcp.json in the current directory)")
        lines.append("restart Claude Code / reload MCP to pick up env")
    if client == "cursor":
        lines.append("reload Cursor MCP / restart to pick up env")
    return lines
