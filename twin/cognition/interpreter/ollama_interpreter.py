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
    INTERPRETATION_TYPES,
    CognitiveAct,
    InterpretationResult,
    InterpretationStatus,
    InterpretedItem,
)
from ..schema import SENSITIVITIES
from ...config import ALL_DOMAINS

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


_ACT_ALIASES = {
    "statement": CognitiveAct.statement,
    "assert": CognitiveAct.statement,
    "assertion": CognitiveAct.statement,
    "claim": CognitiveAct.third_party_claim,
    "third_party": CognitiveAct.third_party_claim,
    "third-party-claim": CognitiveAct.third_party_claim,
    "third_party_claim": CognitiveAct.third_party_claim,
    "question": CognitiveAct.question,
    "hypothesis": CognitiveAct.hypothesis,
    "proposal": CognitiveAct.proposal,
    "suggestion": CognitiveAct.proposal,
    "recommendation": CognitiveAct.proposal,
    "decision": CognitiveAct.decision,
    "chose": CognitiveAct.decision,
    "choice": CognitiveAct.decision,
    "opinion": CognitiveAct.opinion,
    "belief": CognitiveAct.opinion,
    "preference": CognitiveAct.opinion,
}

_TYPE_ALIASES = {
    "rejected alternative": "rejected_alternative",
    "rejected-alternative": "rejected_alternative",
    "alternative": "rejected_alternative",
    "note": "fact",
    "knowledge": "fact",
    "info": "fact",
    "information": "fact",
    "action": "task",
    "todo": "task",
    "commitment": "task",
    "rule": "constraint",
    "policy": "constraint",
    "workflow": "procedure",
    "process": "procedure",
    "habit": "procedure",
    "person": "relationship",
    "people": "relationship",
    "message": "communication_act",
    "utterance": "communication_act",
}

_DOMAIN_ALIASES = {
    "tech": "technical",
    "technology": "technical",
    "engineering": "technical",
    "architecture": "technical",
    "professional": "work",
    "job": "work",
    "company": "work",
    "business": "work",
    "personal": "personal_preferences",
    "prefs": "personal_preferences",
    "assistant": "assistant_preferences",
    "ai": "assistant_preferences",
}


def _as_str_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        text = value.strip()
        return [text] if text else []
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if item is None:
                continue
            text = str(item).strip()
            if text:
                out.append(text)
        return out
    return []


def _as_confidence(value) -> float:
    if value is None or value == "":
        return 0.5
    if isinstance(value, (int, float)):
        n = float(value)
        return max(0.0, min(1.0, n / 100.0 if n > 1.0 else n))
    text = str(value).strip().lower()
    mapping = {
        "very high": 0.95, "high": 0.85, "medium": 0.55, "moderate": 0.55,
        "low": 0.3, "very low": 0.15,
    }
    if text in mapping:
        return mapping[text]
    try:
        n = float(text)
    except ValueError:
        return 0.5
    return max(0.0, min(1.0, n / 100.0 if n > 1.0 else n))


def _coerce_item(raw: dict) -> Optional[InterpretedItem]:
    """Normalize messy LLM fields; return None when the item is unusable."""
    if not isinstance(raw, dict):
        return None
    data = dict(raw)

    mem_type = str(data.get("memory_type") or "fact").strip().lower().replace(" ", "_")
    mem_type = _TYPE_ALIASES.get(mem_type.replace("_", " "), _TYPE_ALIASES.get(mem_type, mem_type))
    if mem_type not in INTERPRETATION_TYPES:
        mem_type = "fact"
    data["memory_type"] = mem_type

    act_raw = str(data.get("cognitive_act") or "statement").strip().lower().replace(" ", "_")
    act = _ACT_ALIASES.get(act_raw.replace("_", "-"), _ACT_ALIASES.get(act_raw))
    if act is None:
        try:
            act = CognitiveAct(act_raw)
        except ValueError:
            act = CognitiveAct.statement
    data["cognitive_act"] = act

    title = str(data.get("title") or "").strip()
    summary = str(data.get("summary") or "").strip()
    if not title and not summary:
        return None
    data["title"] = title or summary[:80]
    data["summary"] = summary or title

    domain = str(data.get("domain") or "technical").strip().lower().replace(" ", "_")
    domain = _DOMAIN_ALIASES.get(domain, domain)
    if domain not in ALL_DOMAINS:
        domain = "technical"
    data["domain"] = domain

    sensitivity = str(data.get("sensitivity") or "internal").strip().lower()
    if sensitivity not in SENSITIVITIES:
        sensitivity = "internal"
    data["sensitivity"] = sensitivity

    data["confidence"] = _as_confidence(data.get("confidence"))
    data["entities"] = _as_str_list(data.get("entities"))
    data["temporal_refs"] = _as_str_list(data.get("temporal_refs"))
    data["unresolved_references"] = _as_str_list(data.get("unresolved_references"))

    evidence = data.get("evidence_span") or data.get("evidence") or data.get("quote") or ""
    data["evidence_span"] = str(evidence).strip()

    for key in ("attributed_to", "project_ref", "ambiguity", "valid_from"):
        if data.get(key) is None:
            continue
        data[key] = str(data[key]).strip() or None

    owner = data.get("speaker_is_owner")
    if isinstance(owner, str):
        low = owner.strip().lower()
        data["speaker_is_owner"] = (
            True if low in ("true", "yes", "1") else
            False if low in ("false", "no", "0") else None
        )
    elif owner is not None and not isinstance(owner, bool):
        data["speaker_is_owner"] = None

    relations = data.get("relations") or []
    clean_rels = []
    if isinstance(relations, list):
        for rel in relations:
            if not isinstance(rel, dict):
                continue
            sub = str(rel.get("subject") or "").strip()
            pred = str(rel.get("predicate") or "").strip()
            obj = str(rel.get("object") or "").strip()
            if sub and pred and obj:
                clean_rels.append(
                    {"subject": sub, "predicate": pred, "object": obj}
                )
    data["relations"] = clean_rels

    # Drop unknown keys so future model fields never trip validation.
    allowed = set(InterpretedItem.model_fields)
    data = {k: v for k, v in data.items() if k in allowed}
    try:
        return InterpretedItem(**data)
    except Exception:
        return None


def _items_from_payload(data: dict) -> tuple[list[InterpretedItem], int]:
    raw_items = data.get("items") or []
    if not isinstance(raw_items, list):
        return [], 0
    items: list[InterpretedItem] = []
    dropped = 0
    for raw in raw_items:
        item = _coerce_item(raw if isinstance(raw, dict) else {})
        if item is None:
            dropped += 1
            continue
        items.append(item)
    return items, dropped


def _parse_model_json(content: str) -> dict:
    """Parse structured-output JSON; tolerate think-tags / markdown fences.

    Thinking models (e.g. qwen3.x) sometimes wrap or precede the JSON object
    even when ``format`` is requested. Fail only when no JSON object remains.
    """
    import re

    raw = (content or "").strip()
    if not raw:
        raise json.JSONDecodeError("empty model content", raw, 0)

    # Drop common chain-of-thought wrappers before parsing.
    raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"<thinking>.*?</thinking>", "", raw, flags=re.DOTALL | re.IGNORECASE)
    raw = re.sub(r"```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
    raw = raw.replace("```", "").strip()

    try:
        data = json.loads(raw)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    start, end = raw.find("{"), raw.rfind("}")
    if start >= 0 and end > start:
        data = json.loads(raw[start : end + 1])
        if isinstance(data, dict):
            return data
    raise json.JSONDecodeError("no JSON object in model content", raw, 0)


def interpret(percept: Percept, text: str, *,
              base_url: str = "http://127.0.0.1:11434",
              model: str = "qwen3.6:latest", client=None,
              chat=None) -> InterpretationResult:
    """Run the cognitive interpreter.

    Prefer passing ``chat`` (a :class:`~twin.cognition.llm.ChatClient`) so
    Ollama *or* OpenAI-compatible providers work. Legacy ``base_url`` /
    ``model`` / ``client`` still build an Ollama chat client.
    """
    if chat is None:
        from ..llm import OllamaChatClient
        chat = OllamaChatClient(base_url, model, client=client)

    data = chat.complete_json(
        system=SYSTEM_PROMPT,
        user=_user_content(percept, text),
        schema=INTERPRETATION_JSON_SCHEMA,
        temperature=0.1,
    )
    items, dropped = _items_from_payload(data)
    status = (InterpretationStatus.interpreted if items
              else InterpretationStatus.empty)
    detail = f"dropped {dropped} malformed item(s)" if dropped else ""
    label = getattr(chat, "name", None) or f"ollama:{model}"
    return InterpretationResult(
        items=items,
        status=status,
        interpreter=label,
        model=getattr(chat, "model", model),
        prompt_version=PROMPT_VERSION,
        schema_version=SCHEMA_VERSION,
        unresolved_references=_as_str_list(data.get("unresolved_references")),
        detail=detail,
    )


def available(base_url: str) -> bool:
    from ...memory.embeddings import ollama_reachable

    return ollama_reachable(base_url)
