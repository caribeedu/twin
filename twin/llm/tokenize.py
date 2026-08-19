"""Token counting via tiktoken (OpenAI's official BPE tokenizer).

Used for preflight estimates. Non-OpenAI models (Claude, Gemini, Ollama) do not
expose a public matching tokenizer; we pick the closest tiktoken encoding and
treat the result as an estimate.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional


@lru_cache(maxsize=16)
def encoding_name_for_model(model: str) -> str:
    """Best-effort tiktoken encoding name for ``model``."""
    import tiktoken

    m = (model or "").strip()
    if m:
        try:
            enc = tiktoken.encoding_for_model(m)
            return enc.name
        except KeyError:
            pass
    low = m.lower()
    if any(k in low for k in ("gpt-4o", "gpt-5", "o1", "o3", "o4", "omni")):
        return "o200k_base"
    # Claude / Gemini / local / unknown — cl100k_base is the common estimate base.
    return "cl100k_base"


@lru_cache(maxsize=8)
def _encoding(name: str):
    import tiktoken

    return tiktoken.get_encoding(name)


def count_tokens(text: str, *, model: str = "", encoding: Optional[str] = None) -> int:
    """Count tokens in ``text`` with tiktoken. Empty → 0."""
    if not text:
        return 0
    name = encoding or encoding_name_for_model(model)
    return len(_encoding(name).encode(text))


def count_messages_tokens(
    *,
    system: str,
    user: str,
    model: str = "",
    overhead: int = 24,
) -> int:
    """Estimate prompt tokens for a system+user chat turn (+ small framing overhead)."""
    enc = encoding_name_for_model(model)
    return (
        count_tokens(system or "", encoding=enc)
        + count_tokens(user or "", encoding=enc)
        + max(0, int(overhead))
    )
