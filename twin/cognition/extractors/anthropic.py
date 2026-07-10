"""Anthropic extractor — optional cloud backend (structured outputs).

Disabled by default in a local-first setup; used only when explicitly
selected (``TWIN_EXTRACTOR=anthropic``) or as the second choice in ``auto``
mode when Ollama is unreachable. Only ever receives PII-masked text.
"""

from __future__ import annotations

import json

from ...sensory.percept import Percept
from ..schema import EXTRACTION_JSON_SCHEMA, ExtractedMemory, ExtractionResult
from .ollama import SYSTEM_PROMPT  # same extraction contract, shared prompt


def extract(percept: Percept, text: str, model: str = "claude-opus-4-8") -> ExtractionResult:
    import anthropic

    client = anthropic.Anthropic()
    user_content = (
        f"Percept type: {percept.percept_type}\n"
        f"Actors: {', '.join(percept.actors) or 'unknown'}\n"
        f"Occurred at: {percept.occurred_at or 'unknown'}\n"
        f"--- BEGIN SOURCE ---\n{text}\n--- END SOURCE ---"
    )
    with client.messages.stream(
        model=model,
        max_tokens=64000,
        system=SYSTEM_PROMPT,
        thinking={"type": "adaptive"},
        output_config={
            "format": {"type": "json_schema", "schema": EXTRACTION_JSON_SCHEMA}
        },
        messages=[{"role": "user", "content": user_content}],
    ) as stream:
        response = stream.get_final_message()

    if response.stop_reason == "refusal":
        return ExtractionResult(memories=[], extractor=f"anthropic:{model}(refused)")

    content = next((b.text for b in response.content if b.type == "text"), "{}")
    data = json.loads(content)
    memories = [ExtractedMemory(**m).normalized() for m in data.get("memories", [])]
    return ExtractionResult(memories=memories, extractor=f"anthropic:{model}")


def available() -> bool:
    """True when the anthropic SDK is importable and a credential is likely present."""
    import os

    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    # `ant auth login` profile on disk also works with a bare client
    from pathlib import Path

    cfg_dir = Path(os.environ.get("ANTHROPIC_CONFIG_DIR", "~/.config/anthropic")).expanduser()
    return (cfg_dir / "credentials").exists()
