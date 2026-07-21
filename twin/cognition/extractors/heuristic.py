"""Conservative lexical detector (v0.7).

This module NO LONGER produces memories. In v0.7 lexical rules may only
*detect* that a span looks like it might carry a decision, task, preference,
constraint or rejected alternative — a routing/prioritization signal, never a
cognitive conclusion. Establishing the memory type, domain, entities, title,
summary and cognitive confidence is the cognitive interpreter's job.

Two consumers use ``scan``:

- ``heuristic`` mode persists each hit as a ``DetectionSignal`` (never a
  ``MemoryItem``);
- the offline *stub interpreter* (the deterministic test/CI stand-in for the
  LLM) turns hits into grounded ``InterpretedItem``s so the interpreter path
  can be exercised without a model.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_DECISION_MARKERS = [
    r"\bdecidimos\b", r"\bdecidiu\b", r"\bdecidido\b", r"\bficou decidido\b",
    r"\bvamos usar\b", r"\bvamos adotar\b", r"\bescolhemos\b", r"\boptamos por\b",
    r"\bwe decided\b", r"\bdecision:\b", r"\bwe(?:'ll| will) use\b", r"\bwe chose\b",
    r"\bagreed to\b", r"\bwe adopted\b",
]
_TASK_MARKERS = [
    r"\btodo\b", r"\baction item\b", r"\bfica respons[aá]vel\b", r"\bvai fazer\b",
    r"\bprecisa (?:fazer|entregar|revisar)\b", r"\btarefa:\b", r"\btask:\b",
    r"\bfollow[- ]up\b", r"\bat[eé] (?:sexta|segunda|ter[cç]a|quarta|quinta|o dia)\b",
]
_PREFERENCE_MARKERS = [
    r"\bprefiro\b", r"\bprefere\b", r"\bpreferimos\b", r"\bprefer\b",
    r"\bsempre us[oa]\b", r"\bgosto de\b", r"\bpadr[aã]o (?:é|eh|sera|será)\b",
]
_CONSTRAINT_MARKERS = [
    r"\bn[aã]o pode(?:mos)?\b", r"\bproibido\b", r"\bmust not\b", r"\brestri[cç][aã]o\b",
    r"\bcompliance\b", r"\bobrigat[oó]rio\b",
]

# A rejected alternative is still a decision — arguably the more valuable half
# of one. Checked BEFORE plain decision markers so "instead of Redis we'll use
# Postgres" is detected as a rejected alternative.
_REJECTED_ALTERNATIVE_MARKERS = [
    r"\bdecided against\b", r"\brejected (?:because|in favor of)\b",
    r"\binstead of\b.{1,80}\b(?:use|using|went with|we(?:'ll| will) use)\b",
    r"\bnot going with\b", r"\bwe won'?t use\b", r"\bruled out\b",
    r"\bdescartamos\b", r"\brejeitamos\b", r"\bdecidimos n[aã]o usar\b",
    r"\bem vez de\b.{1,80}\b(?:usar|vamos usar|usaremos)\b",
]

_MARKER_SETS = [
    ("rejected_alternative",
     [re.compile(p, re.IGNORECASE) for p in _REJECTED_ALTERNATIVE_MARKERS]),
    ("decision", [re.compile(p, re.IGNORECASE) for p in _DECISION_MARKERS]),
    ("task", [re.compile(p, re.IGNORECASE) for p in _TASK_MARKERS]),
    ("preference", [re.compile(p, re.IGNORECASE) for p in _PREFERENCE_MARKERS]),
    ("constraint", [re.compile(p, re.IGNORECASE) for p in _CONSTRAINT_MARKERS]),
]

# Capitalized multiword sequences and CamelCase / known-tech tokens.
_ENTITY_RE = re.compile(
    r"\b([A-Z][a-zA-Z0-9]+(?:\s+[A-Z][a-zA-Z0-9]+)*|[a-z]+[A-Z][a-zA-Z]+)\b"
)
_ENTITY_STOPWORDS = {
    "The", "This", "That", "When", "Then", "After", "Before", "Also", "Como",
    "Para", "Isso", "Essa", "Esse", "Sobre", "Hoje", "Amanhã", "Ontem", "OK",
    "TODO", "Action", "Task", "Summary", "Decision",
}

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
# detection confidence — deliberately low; a detection is a hint, not a claim
DETECTION_CONFIDENCE = 0.5


@dataclass
class Detected:
    kind: str                 # candidate category (a hint, never a memory type)
    span: str                 # verbatim sentence that triggered the hit
    entities: list[str] = field(default_factory=list)
    confidence: float = DETECTION_CONFIDENCE


def _entities(sentence: str) -> list[str]:
    found = []
    for m in _ENTITY_RE.finditer(sentence):
        name = m.group(1).strip()
        if name in _ENTITY_STOPWORDS or len(name) < 3:
            continue
        if sentence.strip().startswith(name + ":"):
            continue
        found.append(name)
    seen: set[str] = set()
    out = []
    for n in found:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out[:8]


def scan(text: str) -> list[Detected]:
    """Detect candidate spans in ``text`` — one hit per sentence, first
    matching category wins. The span is a verbatim excerpt of ``text`` so a
    downstream interpreter's evidence stays grounded."""
    out: list[Detected] = []
    seen: set[str] = set()
    for raw_sentence in _SENTENCE_SPLIT.split(text or ""):
        sentence = raw_sentence.strip()
        if not 15 <= len(sentence) <= 600:
            continue
        for kind, patterns in _MARKER_SETS:
            if not any(p.search(sentence) for p in patterns):
                continue
            key = sentence.lower()
            if key in seen:
                break
            seen.add(key)
            out.append(Detected(kind=kind, span=sentence, entities=_entities(sentence)))
            break
    return out
