"""LLM extractor backed by the Anthropic API (structured outputs).

Only ever receives PII-masked text (see runner). Requires an Anthropic
credential (``ANTHROPIC_API_KEY`` or an ``ant auth login`` profile); callers
should catch failures and fall back to the heuristic extractor.
"""

from __future__ import annotations

import json

from ..models import Source
from .schema import EXTRACTION_JSON_SCHEMA, ExtractedMemory, ExtractionResult

SYSTEM_PROMPT = """\
You are a memory-extraction engine for a personal cognitive system. You read a
document, meeting transcript or chat log belonging to the user and extract
durable, reusable memories about the user's professional/technical life.

Extract only what is actually supported by the text:
- decisions (what was decided, rationale, rejected alternatives if stated)
- tasks and commitments (who will do what, deadlines)
- facts about projects, systems and people
- stable preferences (technical or communication style)
- beliefs/opinions (things that may change over time)
- procedures (how the user does something)
- constraints (things that must not be done)
- events (meetings, incidents, milestones)

Rules:
- evidence_quote MUST be a verbatim excerpt from the input that supports the memory.
- Do NOT invent information. If the text is ambiguous, lower the confidence.
- Prefer few high-value memories over many trivial ones.
- domain: use "work" for team/company context, "technical" for technology
  decisions and architecture, "personal_preferences" for the user's general
  preferences, "assistant_preferences" for how the user wants AI assistants to
  behave. Never place professional content in personal domains.
- sensitivity: "internal" by default; "private" for anything the user would
  not want quoted outside the original context; "restricted" for secrets.
- relations: subject/object are entity names, predicate is a short snake_case
  verb (works_on, prefers, affects, produced, assigned_to, uses, part_of).
- Keep titles under 90 characters. Summaries are 1-3 sentences, self-contained.
- Answer in the language of the source text (pt-BR sources → pt-BR summaries).
"""


def extract(source: Source, masked_text: str, model: str = "claude-opus-4-8") -> ExtractionResult:
    import anthropic

    client = anthropic.Anthropic()
    user_content = (
        f"Source type: {source.source_type}\n"
        f"Participants: {', '.join(source.participants) or 'unknown'}\n"
        f"Produced at: {source.created_at or 'unknown'}\n"
        f"--- BEGIN SOURCE ---\n{masked_text}\n--- END SOURCE ---"
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
        return ExtractionResult(memories=[], extractor=f"llm:{model}(refused)")

    text = next((b.text for b in response.content if b.type == "text"), "{}")
    data = json.loads(text)
    memories = [ExtractedMemory(**m).normalized() for m in data.get("memories", [])]
    return ExtractionResult(memories=memories, extractor=f"llm:{model}")


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
