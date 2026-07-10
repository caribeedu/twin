"""Ollama extractor — local LLM extraction, nothing leaves the machine.

Uses Ollama's structured outputs (the ``format`` field takes a JSON schema)
against ``/api/chat``. Default model comes from ``TWIN_OLLAMA_MODEL``.
"""

from __future__ import annotations

import json

from ...sensory.percept import Percept
from ..schema import EXTRACTION_JSON_SCHEMA, ExtractedMemory, ExtractionResult

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
- Respond with JSON only, matching the provided schema.
"""


def extract(percept: Percept, text: str, base_url: str = "http://127.0.0.1:11434",
            model: str = "qwen3:8b", client=None) -> ExtractionResult:
    import httpx

    http = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=600)
    user_content = (
        f"Percept type: {percept.percept_type}\n"
        f"Actors: {', '.join(percept.actors) or 'unknown'}\n"
        f"Occurred at: {percept.occurred_at or 'unknown'}\n"
        f"--- BEGIN SOURCE ---\n{text}\n--- END SOURCE ---"
    )
    resp = http.post("/api/chat", json={
        "model": model,
        "stream": False,
        "format": EXTRACTION_JSON_SCHEMA,
        "options": {"temperature": 0.1},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    })
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    data = json.loads(content)
    memories = [ExtractedMemory(**m).normalized() for m in data.get("memories", [])]
    return ExtractionResult(memories=memories, extractor=f"ollama:{model}")


def available(base_url: str) -> bool:
    from ...memory.embeddings import ollama_reachable

    return ollama_reachable(base_url)
