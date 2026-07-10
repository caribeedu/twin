"""Rule-based extractor — the no-API-key fallback.

Scans sentences for decision/task/preference markers in pt-BR and English.
Deliberately low confidence: everything it produces lands in the review queue
so a human confirms before the memory is trusted.
"""

from __future__ import annotations

import re

from ...sensory.percept import Percept
from ..schema import ExtractedMemory, ExtractionResult

_DECISION_MARKERS = [
    r"\bdecidimos\b", r"\bdecidiu\b", r"\bdecidido\b", r"\bficou decidido\b",
    r"\bvamos usar\b", r"\bvamos adotar\b", r"\bescolhemos\b", r"\boptamos por\b",
    r"\bwe decided\b", r"\bdecision:\b", r"\bwe(?:'ll| will) use\b", r"\bwe chose\b",
    r"\bagreed to\b",
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

_MARKER_SETS = [
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


def _entities(sentence: str) -> list[str]:
    found = []
    for m in _ENTITY_RE.finditer(sentence):
        name = m.group(1).strip()
        if name in _ENTITY_STOPWORDS or len(name) < 3:
            continue
        # drop a leading speaker label ("João: ...")
        if sentence.strip().startswith(name + ":"):
            continue
        found.append(name)
    # dedupe, keep order
    seen: set[str] = set()
    out = []
    for n in found:
        if n.lower() not in seen:
            seen.add(n.lower())
            out.append(n)
    return out[:8]


def extract(percept: Percept) -> ExtractionResult:
    memories: list[ExtractedMemory] = []
    seen_titles: set[str] = set()
    default_domain = percept.privacy_hints.get(
        "domain_hint",
        "technical" if percept.percept_type == "document" else "work",
    )
    for raw_sentence in _SENTENCE_SPLIT.split(percept.content):
        sentence = raw_sentence.strip()
        if not 15 <= len(sentence) <= 600:
            continue
        for mem_type, patterns in _MARKER_SETS:
            if not any(p.search(sentence) for p in patterns):
                continue
            title = sentence if len(sentence) <= 90 else sentence[:87] + "..."
            if title.lower() in seen_titles:
                break
            seen_titles.add(title.lower())
            memories.append(
                ExtractedMemory(
                    type=mem_type,
                    title=title,
                    summary=sentence,
                    domain=default_domain,
                    sensitivity="internal",
                    confidence=0.5,  # heuristic → always below review threshold
                    entities=_entities(sentence),
                    evidence_quote=sentence,
                ).normalized()
            )
            break  # one memory per sentence, first matching type wins
    return ExtractionResult(memories=memories, extractor="heuristic")
