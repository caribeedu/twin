"""Guided first-run setup for Twin (v1.1)."""

from __future__ import annotations

import os

from ..config import Config
from ..memory.embeddings import ollama_reachable
from . import ux


OLLAMA_DOWNLOAD = "https://ollama.com/download"


def _list_ollama_models(url: str) -> list[str]:
    try:
        import httpx
        tags = httpx.get(f"{url.rstrip('/')}/api/tags", timeout=5).json()
        return [m.get("name", "") for m in tags.get("models", []) if m.get("name")]
    except Exception:
        return []


def run_setup_wizard(cfg: Config, *, interactive: bool = True) -> list[str]:
    """Ensure home exists and walk the user through Ollama/model config.

    Returns human-readable summary lines. When ``interactive`` is False (CI),
    only creates defaults and reports status — never blocks on prompts.
    """
    lines: list[str] = []
    cfg.ensure_home()
    env_path = cfg.home / "env"

    ux.print_rule("Twin setup")
    ux.print_panel(
        "Local-first cognitive OS.\n"
        "This wizard creates your home, copies default policies/judgment,\n"
        "checks Ollama, and saves model settings to ~/.twin/env.",
        title="welcome",
    )
    ux.print_kv([
        ("home", str(cfg.home)),
        ("defaults", "twin/defaults/*.yaml → policies, judgment, calibration"),
        ("env file", str(env_path)),
    ])
    ux.print_ok(f"home ready → {cfg.home}")
    lines.append(f"home={cfg.home}")

    url = cfg.ollama_url
    model = cfg.ollama_model
    embed = cfg.ollama_embed_model

    if not interactive or not __import__("sys").stdin.isatty():
        reachable = ollama_reachable(url)
        lines.append(f"ollama_url={url} reachable={reachable}")
        ux.print_panel(
            f"url        {url}\n"
            f"reachable  {reachable}\n"
            f"model      {model}\n"
            f"embed      {embed}\n"
            f"download   {OLLAMA_DOWNLOAD}",
            title="ollama (non-interactive)",
        )
        if not reachable:
            ux.print_warn(f"Ollama not reachable at {url}")
            ux.print_dim(f"Install: {OLLAMA_DOWNLOAD}")
            ux.print_dim("Then: ollama serve && twin setup ollama")
        else:
            ux.print_ok(f"Ollama reachable at {url}")
        return lines

    ux.print_panel(
        "Ollama runs the local cognitive interpreter + embeddings.\n"
        f"Download: {OLLAMA_DOWNLOAD}\n"
        "Then start with: ollama serve",
        title="ollama",
    )

    if not ollama_reachable(url):
        ux.print_warn(f"No Ollama at {url}")
        if ux.prompt_yes_no("Change server URL now?", default=True):
            url = ux.prompt_line("Ollama URL", default=url)
        if not ollama_reachable(url):
            ux.print_err(f"Still unreachable: {url}")
            ux.print_dim("Start it with:  ollama serve")
            ux.print_dim("Or Docker:      docker compose up -d ollama")
            if not ux.prompt_yes_no("Save this URL anyway and continue?", default=True):
                ux.write_env_file(env_path, {
                    "TWIN_OLLAMA_URL": url,
                    "TWIN_OLLAMA_MODEL": model,
                    "TWIN_OLLAMA_EMBED_MODEL": embed,
                })
                lines.append("setup_aborted=ollama_unreachable")
                return lines
    else:
        ux.print_ok(f"Ollama reachable at {url}")
        if not ux.prompt_yes_no("Keep this URL?", default=True):
            url = ux.prompt_line("Ollama URL", default=url)

    available = _list_ollama_models(url)
    if available:
        model_lines = "\n".join(f"  • {name}" for name in available[:12])
        if len(available) > 12:
            model_lines += f"\n  … +{len(available) - 12} more"
        ux.print_panel(model_lines, title=f"models on server ({len(available)})")
    else:
        ux.print_warn("No models listed (server down or empty).")
        ux.print_dim("Pull defaults later with: twin setup ollama")

    bases = {n.split(":")[0] for n in available}
    if model.split(":")[0] not in bases and available:
        ux.print_warn(f"Chat model {model} not found on server")
        suggestion = next(
            (n for n in available if "embed" not in n.lower()),
            available[0],
        )
        model = ux.prompt_line("Chat / extraction model", default=suggestion)
    else:
        model = ux.prompt_line("Chat / extraction model", default=model)

    if embed.split(":")[0] not in bases and available:
        emb_guess = next(
            (n for n in available if "embed" in n.lower() or "nomic" in n.lower()),
            embed,
        )
        ux.print_warn(f"Embed model {embed} not found on server")
        embed = ux.prompt_line("Embedding model", default=emb_guess)
    else:
        embed = ux.prompt_line("Embedding model", default=embed)

    ux.write_env_file(env_path, {
        "TWIN_OLLAMA_URL": url,
        "TWIN_OLLAMA_MODEL": model,
        "TWIN_OLLAMA_EMBED_MODEL": embed,
    })
    os.environ["TWIN_OLLAMA_URL"] = url
    os.environ["TWIN_OLLAMA_MODEL"] = model
    os.environ["TWIN_OLLAMA_EMBED_MODEL"] = embed
    cfg.ollama_url = url
    cfg.ollama_model = model
    cfg.ollama_embed_model = embed

    ux.print_panel(
        f"TWIN_OLLAMA_URL={url}\n"
        f"TWIN_OLLAMA_MODEL={model}\n"
        f"TWIN_OLLAMA_EMBED_MODEL={embed}\n"
        f"saved → {env_path}",
        title="saved env",
    )
    ux.print_ok(f"saved {env_path}")

    if ollama_reachable(url) and ux.prompt_yes_no(
        "Pull missing models now (twin setup ollama)?", default=True,
    ):
        from .ops import setup_ollama
        with ux.spinner("Pulling models…"):
            pull_lines = setup_ollama(cfg)
        if pull_lines:
            ux.print_panel("\n".join(pull_lines), title="pull")
        lines.extend(pull_lines)

    lines.append(f"env={env_path}")
    return lines
