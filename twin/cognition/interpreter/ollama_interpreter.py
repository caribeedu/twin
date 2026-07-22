"""Local LLM cognitive interpreter (v0.7 production path).

Uses Ollama structured outputs against ``/api/chat`` — nothing leaves the
machine. The prompt makes the interpreter do the work lexical rules cannot:
tell a decision from a proposal, attribute a claim to the right speaker,
ground every item in a verbatim span, and *report* ambiguity instead of
guessing through it.
"""

from __future__ import annotations

import json
from typing import Optional

from ...sensory.percept import Percept
from .schema import (
    INTERPRETATION_JSON_SCHEMA,
    InterpretationResult,
    InterpretationStatus,
    InterpretedItem,
)

PROMPT_VERSION = "interpret-v1"
SCHEMA_VERSION = "1"

SYSTEM_PROMPT = """\
You are the cognitive interpreter of a personal cognitive system. You read a
document, meeting transcript or chat log belonging to the user and identify
what it MEANS, cataloguing durable, reusable items about the user's
professional and technical life. You do not summarize; you interpret.

For every item you catalogue, decide the COGNITIVE ACT that produced it:
- decision: a settled choice the parties actually made;
- proposal: a choice suggested but NOT yet made (never a decision);
- question: something asked, not asserted;
- hypothesis: a tentative idea, explicitly uncertain;
- opinion: a stance or judgement, not a verifiable fact;
- third_party_claim: something asserted by someone OTHER than the account
  owner — attribute it, never adopt it as the user's own knowledge;
- statement: a plain factual assertion by the author.

Then classify memory_type: decision, task, fact, event, preference, belief,
constraint, procedure, relationship, communication_act, or
rejected_alternative (an option considered and turned down).

Hard rules:
- evidence_span MUST be a verbatim excerpt from the source that supports the
  item. If you cannot ground an item in the text, do NOT emit it.
- attributed_to is the person the item comes from (a speaker/author name from
  the source). Set speaker_is_owner true only when the account owner is
  clearly the author; otherwise false or null.
- Never invent facts, names, dates or projects. If a reference is unclear
  (an unnamed "they", an unspecified deadline, an ambiguous pronoun), list it
  in unresolved_references and, when the whole item is ambiguous, fill
  ambiguity with the competing readings — do not resolve it by guessing.
- A proposal that was later accepted is a decision only if the acceptance is
  in the text; otherwise it stays a proposal.
- domain: "work" for team/company context, "technical" for technology and
  architecture, "personal_preferences" for the user's own preferences,
  "assistant_preferences" for how the user wants AI assistants to behave.
  Never place professional content in personal domains.
- sensitivity: "internal" by default; "private" for anything not to be quoted
  outside its context; "restricted" for secrets.
- confidence is your confidence in the INTERPRETATION, not a trust score.
- Answer in the language of the source. Respond with JSON only, matching the
  provided schema. Prefer few well-grounded items over many shallow ones.
"""


def _user_content(percept: Percept, text: str) -> str:
    return (
        f"Percept type: {percept.percept_type}\n"
        f"Known actors: {', '.join(percept.actors) or 'unknown'}\n"
        f"Occurred at: {percept.occurred_at or 'unknown'}\n"
        f"--- BEGIN SOURCE ---\n{text}\n--- END SOURCE ---"
    )


def interpret(percept: Percept, text: str, *,
              base_url: str = "http://127.0.0.1:11434",
              model: str = "qwen3.6:latest", client=None) -> InterpretationResult:
    import httpx

    http = client or httpx.Client(base_url=base_url.rstrip("/"), timeout=600)
    resp = http.post("/api/chat", json={
        "model": model,
        "stream": False,
        "format": INTERPRETATION_JSON_SCHEMA,
        "options": {"temperature": 0.1},
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": _user_content(percept, text)},
        ],
    })
    resp.raise_for_status()
    content = resp.json()["message"]["content"]
    data = json.loads(content)
    items = [InterpretedItem(**it) for it in data.get("items", [])]
    status = (InterpretationStatus.interpreted if items
              else InterpretationStatus.empty)
    return InterpretationResult(
        items=items,
        status=status,
        interpreter=f"ollama:{model}",
        model=model,
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        unresolved_references=list(data.get("unresolved_references", []) or []),
    )


def available(base_url: str) -> bool:
    from ...memory.embeddings import ollama_reachable

    return ollama_reachable(base_url)
