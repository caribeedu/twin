"""Guided first-run setup for Twin (+).

Encourages local Ollama by default; optionally configures Anthropic,
Gemini, or any OpenAI-compatible chat + embedding endpoint.
"""

from __future__ import annotations

import os

from ..llm import PROVIDER_PRESETS, list_wizard_providers, provider_kind
from ..config import Config
from twin.store.embeddings import (
    ollama_reachable,
    openai_compat_reachable,
    sanitize_base_url,
)
from . import ux


OLLAMA_DOWNLOAD = "https://ollama.com/download"

# Interactive menu choice → preset name
_CHOICE_TO_PROVIDER = {
    "1": "ollama",
    "2": "openai_compatible",
    "3": "anthropic",
    "4": "gemini",
}


def _list_ollama_models(url: str) -> list[str]:
    try:
        import httpx
        base = sanitize_base_url(url).rstrip("/")
        if not base:
            return []
        tags = httpx.get(f"{base}/api/tags", timeout=5).json()
        return [m.get("name", "") for m in tags.get("models", []) if m.get("name")]
    except Exception:
        return []


def _apply_env(cfg: Config, values: dict[str, str], env_path) -> None:
    ux.write_env_file(env_path, values)
    for k, v in values.items():
        if v is not None:
            os.environ[k] = str(v)
    # refresh live cfg fields used later in the same process
    if "TWIN_LLM_PROVIDER" in values:
        cfg.llm_provider = values["TWIN_LLM_PROVIDER"]
    if "TWIN_LLM_BASE_URL" in values:
        cfg.llm_base_url = values["TWIN_LLM_BASE_URL"]
    if "TWIN_LLM_MODEL" in values:
        cfg.llm_model = values["TWIN_LLM_MODEL"]
    if "TWIN_LLM_API_KEY" in values:
        cfg.llm_api_key = values["TWIN_LLM_API_KEY"]
    if "TWIN_OLLAMA_URL" in values:
        cfg.ollama_url = values["TWIN_OLLAMA_URL"]
    if "TWIN_OLLAMA_MODEL" in values:
        cfg.ollama_model = values["TWIN_OLLAMA_MODEL"]
    if "TWIN_OLLAMA_EMBED_MODEL" in values:
        cfg.ollama_embed_model = values["TWIN_OLLAMA_EMBED_MODEL"]
    if "TWIN_EMBEDDER" in values:
        cfg.embedder = values["TWIN_EMBEDDER"]
    if "TWIN_EMBED_BASE_URL" in values:
        cfg.embed_base_url = values["TWIN_EMBED_BASE_URL"]
    if "TWIN_EMBED_MODEL" in values:
        cfg.embed_model = values["TWIN_EMBED_MODEL"]
    if "TWIN_EMBED_API_KEY" in values:
        cfg.embed_api_key = values["TWIN_EMBED_API_KEY"]


def _setup_ollama_flow(cfg: Config, env_path, *, interactive: bool) -> list[str]:
    lines: list[str] = []
    url = sanitize_base_url(cfg.ollama_url)
    model = cfg.resolved_llm_model
    embed = cfg.resolved_embed_model

    if not interactive:
        reachable = ollama_reachable(url)
        lines.append(f"provider=ollama url={url} reachable={reachable}")
        ux.print_panel(
            f"provider   ollama (recommended)\n"
            f"url        {url}\n"
            f"reachable  {reachable}\n"
            f"chat       {model}\n"
            f"embed      {embed}\n"
            f"download   {OLLAMA_DOWNLOAD}",
            title="models (non-interactive)",
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
        title="ollama (recommended)",
    )

    if not ollama_reachable(url):
        ux.print_warn(f"No Ollama at {url}")
        if ux.prompt_yes_no("Change server URL now?", default=True):
            url = sanitize_base_url(ux.prompt_line("Ollama URL", default=url))
        if not ollama_reachable(url):
            ux.print_err(f"Still unreachable: {url}")
            ux.print_dim("Start it with:  ollama serve")
            ux.print_dim("Or Docker:      docker compose up -d ollama")
            if not ux.prompt_yes_no("Save this URL anyway and continue?", default=True):
                _apply_env(cfg, {
                    "TWIN_LLM_PROVIDER": "ollama",
                    "TWIN_OLLAMA_URL": url,
                    "TWIN_OLLAMA_MODEL": model,
                    "TWIN_OLLAMA_EMBED_MODEL": embed,
                    "TWIN_EMBEDDER": "auto",
                }, env_path)
                lines.append("setup_aborted=ollama_unreachable")
                return lines
    else:
        ux.print_ok(f"Ollama reachable at {url}")
        if not ux.prompt_yes_no("Keep this URL?", default=True):
            url = sanitize_base_url(ux.prompt_line("Ollama URL", default=url))

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

    values = {
        "TWIN_LLM_PROVIDER": "ollama",
        "TWIN_OLLAMA_URL": url,
        "TWIN_OLLAMA_MODEL": model,
        "TWIN_OLLAMA_EMBED_MODEL": embed,
        "TWIN_LLM_MODEL": model,
        "TWIN_EMBED_MODEL": embed,
        "TWIN_EMBEDDER": "auto",
    }
    _apply_env(cfg, values, env_path)
    ux.print_panel(
        "\n".join(f"{k}={v}" for k, v in values.items()) + f"\nsaved → {env_path}",
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

    lines.append(f"provider=ollama env={env_path}")
    return lines


def _setup_openai_compat_flow(cfg: Config, env_path, *, interactive: bool) -> list[str]:
    lines: list[str] = []
    base = cfg.llm_base_url or "https://api.openai.com/v1"
    model = cfg.llm_model or "gpt-4o-mini"
    embed = cfg.embed_model or "text-embedding-3-small"
    key = cfg.llm_api_key or os.environ.get("OPENAI_API_KEY", "")

    if not interactive:
        reachable = openai_compat_reachable(base, key)
        lines.append(f"provider=openai_compatible url={base} reachable={reachable}")
        ux.print_panel(
            f"provider   openai_compatible\n"
            f"url        {base}\n"
            f"reachable  {reachable}\n"
            f"chat       {model}\n"
            f"embed      {embed}\n"
            f"api_key    {'set' if key else 'missing'}",
            title="models (non-interactive)",
        )
        return lines

    ux.print_panel(
        "OpenAI-compatible APIs: OpenAI, Azure OpenAI, Groq, Together,\n"
        "Fireworks, OpenRouter, DeepSeek, Mistral, xAI, LM Studio, vLLM…\n"
        "Tip: set TWIN_LLM_PROVIDER=groq|openrouter|… for preset URLs.\n"
        "Prefer local open models when you can — this path is opt-in.",
        title="openai-compatible",
    )
    base = sanitize_base_url(ux.prompt_line("API base URL", default=base))
    key = ux.prompt_line("API key (leave empty if local/unauthenticated)", default=key)
    model = ux.prompt_line("Chat / extraction model", default=model)
    embed = ux.prompt_line("Embedding model", default=embed)

    if not openai_compat_reachable(base, key):
        ux.print_warn(f"Could not reach models endpoint at {base}")
        if not ux.prompt_yes_no("Save anyway?", default=True):
            lines.append("setup_aborted=openai_unreachable")
            return lines
    else:
        ux.print_ok(f"Endpoint reachable at {base}")

    values = {
        "TWIN_LLM_PROVIDER": "openai_compatible",
        "TWIN_LLM_BASE_URL": base,
        "TWIN_LLM_MODEL": model,
        "TWIN_LLM_API_KEY": key,
        "TWIN_EMBEDDER": "openai_compatible",
        "TWIN_EMBED_BASE_URL": base,
        "TWIN_EMBED_MODEL": embed,
        "TWIN_EMBED_API_KEY": key,
        "TWIN_EXTRACTOR": "auto",
    }
    _apply_env(cfg, values, env_path)
    shown = {k: ("***" if "KEY" in k and v else v) for k, v in values.items()}
    ux.print_panel(
        "\n".join(f"{k}={v}" for k, v in shown.items()) + f"\nsaved → {env_path}",
        title="saved env",
    )
    ux.print_ok(f"saved {env_path}")
    ux.print_dim("After changing embed models, run: twin reindex")
    lines.append(f"provider=openai_compatible env={env_path}")
    return lines


def _prompt_embed_backend(cfg: Config) -> tuple[str, str, str, str]:
    """Anthropic has no embeddings — ask Ollama / OpenAI / Gemini / hash."""
    ux.print_legend([
        ("1", "Ollama embeddings (recommended if you have Ollama)"),
        ("2", "OpenAI-compatible embeddings"),
        ("3", "Google Gemini embeddings"),
        ("4", "Hash fallback (offline, weaker search)"),
    ], title="embeddings (Anthropic has none)")
    choice = ux.read_key("  Choose [1/2/3/4] ", allowed="1234")
    if choice == "2":
        base = ux.prompt_line(
            "Embed API base URL", default="https://api.openai.com/v1",
        )
        key = ux.prompt_line(
            "Embed API key",
            default=cfg.embed_api_key or os.environ.get("OPENAI_API_KEY", ""),
        )
        model = ux.prompt_line("Embedding model", default="text-embedding-3-small")
        return "openai_compatible", base, model, key
    if choice == "3":
        key = ux.prompt_line(
            "Gemini API key",
            default=(
                cfg.embed_api_key
                or os.environ.get("GEMINI_API_KEY", "")
                or os.environ.get("GOOGLE_API_KEY", "")
            ),
        )
        model = ux.prompt_line("Embedding model", default="text-embedding-004")
        return "gemini", "https://generativelanguage.googleapis.com", model, key
    if choice == "4":
        return "hash", "", "", ""
    url = sanitize_base_url(ux.prompt_line("Ollama URL", default=cfg.ollama_url))
    model = ux.prompt_line(
        "Embedding model", default=cfg.ollama_embed_model or "nomic-embed-text",
    )
    return "ollama", url, model, ""


def _setup_anthropic_flow(cfg: Config, env_path, *, interactive: bool) -> list[str]:
    lines: list[str] = []
    preset = PROVIDER_PRESETS["anthropic"]
    base = cfg.llm_base_url or preset["base"]
    model = cfg.llm_model or preset["default_model"]
    key = (
        cfg.llm_api_key
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )

    if not interactive:
        lines.append(f"provider=anthropic url={base} model={model}")
        ux.print_panel(
            f"provider   anthropic (Claude)\n"
            f"url        {base}\n"
            f"chat       {model}\n"
            f"api_key    {'set' if key else 'missing'}\n"
            f"embed      (configure separately — Anthropic has no embeddings)",
            title="models (non-interactive)",
        )
        return lines

    ux.print_panel(
        "Anthropic Messages API (Claude).\n"
        "Chat uses ANTHROPIC_API_KEY. Embeddings need a separate backend\n"
        "(Ollama / OpenAI-compatible / Gemini / hash).",
        title="anthropic",
    )
    key = ux.prompt_line("Anthropic API key", default=key)
    model = ux.prompt_line("Claude model", default=model)
    emb_kind, emb_base, emb_model, emb_key = _prompt_embed_backend(cfg)

    values: dict[str, str] = {
        "TWIN_LLM_PROVIDER": "anthropic",
        "TWIN_LLM_BASE_URL": base,
        "TWIN_LLM_MODEL": model,
        "TWIN_LLM_API_KEY": key,
        "TWIN_EXTRACTOR": "auto",
        "TWIN_EMBEDDER": emb_kind,
    }
    if emb_kind == "ollama":
        values["TWIN_OLLAMA_URL"] = emb_base or cfg.ollama_url
        values["TWIN_OLLAMA_EMBED_MODEL"] = emb_model
        values["TWIN_EMBED_MODEL"] = emb_model
    elif emb_kind != "hash":
        values["TWIN_EMBED_BASE_URL"] = emb_base
        values["TWIN_EMBED_MODEL"] = emb_model
        values["TWIN_EMBED_API_KEY"] = emb_key

    _apply_env(cfg, values, env_path)
    shown = {k: ("***" if "KEY" in k and v else v) for k, v in values.items()}
    ux.print_panel(
        "\n".join(f"{k}={v}" for k, v in shown.items()) + f"\nsaved → {env_path}",
        title="saved env",
    )
    ux.print_ok(f"saved {env_path}")
    ux.print_dim("After changing embed models, run: twin reindex")
    lines.append(f"provider=anthropic env={env_path}")
    return lines


def _setup_gemini_flow(cfg: Config, env_path, *, interactive: bool) -> list[str]:
    lines: list[str] = []
    preset = PROVIDER_PRESETS["gemini"]
    base = cfg.llm_base_url or preset["base"]
    model = cfg.llm_model or preset["default_model"]
    key = (
        cfg.llm_api_key
        or os.environ.get("GEMINI_API_KEY", "")
        or os.environ.get("GOOGLE_API_KEY", "")
    )
    embed = cfg.embed_model or "text-embedding-004"

    if not interactive:
        lines.append(f"provider=gemini url={base} model={model}")
        ux.print_panel(
            f"provider   gemini\n"
            f"url        {base}\n"
            f"chat       {model}\n"
            f"embed      {embed}\n"
            f"api_key    {'set' if key else 'missing'}",
            title="models (non-interactive)",
        )
        return lines

    ux.print_panel(
        "Google Gemini generateContent + embedContent.\n"
        "Uses GEMINI_API_KEY or GOOGLE_API_KEY.",
        title="gemini",
    )
    key = ux.prompt_line("Gemini / Google API key", default=key)
    model = ux.prompt_line("Chat model", default=model)
    embed = ux.prompt_line("Embedding model", default=embed)

    values = {
        "TWIN_LLM_PROVIDER": "gemini",
        "TWIN_LLM_BASE_URL": base,
        "TWIN_LLM_MODEL": model,
        "TWIN_LLM_API_KEY": key,
        "TWIN_EMBEDDER": "gemini",
        "TWIN_EMBED_BASE_URL": base,
        "TWIN_EMBED_MODEL": embed,
        "TWIN_EMBED_API_KEY": key,
        "TWIN_EXTRACTOR": "auto",
    }
    _apply_env(cfg, values, env_path)
    shown = {k: ("***" if "KEY" in k and v else v) for k, v in values.items()}
    ux.print_panel(
        "\n".join(f"{k}={v}" for k, v in shown.items()) + f"\nsaved → {env_path}",
        title="saved env",
    )
    ux.print_ok(f"saved {env_path}")
    ux.print_dim("After changing embed models, run: twin reindex")
    lines.append(f"provider=gemini env={env_path}")
    return lines


def run_setup_wizard(cfg: Config, *, interactive: bool = True) -> list[str]:
    """Ensure home exists and configure chat + embedding providers.

    Returns human-readable summary lines. When ``interactive`` is False (CI),
    only creates defaults and reports status — never blocks on prompts.
    """
    lines: list[str] = []
    cfg.ensure_home()
    env_path = cfg.home / "env"

    ux.print_rule("Twin setup")
    ux.print_panel(
        "Local-first cognitive OS.\n"
        "We create your home, copy default policies/judgment, and configure\n"
        "the LLM used for extraction/observer plus the embedding model.\n"
        "Ollama (local) is recommended; Anthropic / Gemini / OpenAI-compat optional.",
        title="welcome",
    )
    ux.print_kv([
        ("home", str(cfg.home)),
        ("defaults", "twin/defaults/*.yaml → policies, judgment, calibration"),
        ("env file", str(env_path)),
    ])
    ux.print_ok(f"home ready → {cfg.home}")
    lines.append(f"home={cfg.home}")

    provider = cfg.normalized_llm_provider
    kind = provider_kind(provider)
    interactive_ok = interactive and __import__("sys").stdin.isatty()

    if interactive_ok:
        legend = list_wizard_providers()
        ux.print_legend(legend, title="LLM provider")
        choice = ux.read_key("  Choose [1/2/3/4] ", allowed="1234")
        provider = _CHOICE_TO_PROVIDER.get(choice, "ollama")
        kind = provider_kind(provider)

    flow_interactive = interactive_ok
    if kind == "openai_compatible" and provider != "ollama":
        lines.extend(_setup_openai_compat_flow(
            cfg, env_path, interactive=flow_interactive,
        ))
    elif kind == "anthropic":
        lines.extend(_setup_anthropic_flow(
            cfg, env_path, interactive=flow_interactive,
        ))
    elif kind == "gemini":
        lines.extend(_setup_gemini_flow(
            cfg, env_path, interactive=flow_interactive,
        ))
    else:
        lines.extend(_setup_ollama_flow(
            cfg, env_path, interactive=flow_interactive,
        ))

    return lines
