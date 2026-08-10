"""Deterministic evidence-span grounding.

An interpreted item is only allowed into the pipeline if its ``evidence_span``
is a **verbatim** excerpt of the text the interpreter actually read. The model
is never trusted to declare that a span is literal — we check it ourselves,
against the *masked* text (the same bytes the interpreter received), so PII
placeholders line up and no removed PII can slip back in through a "quote".

Normalization is limited to operationally-safe differences that never turn a
paraphrase into a match: Unicode form, line endings, collapsed runs of
whitespace, and typographic → straight quotes. Comparison is case-insensitive
(models routinely re-case), but no semantic similarity, stemming or fuzzy
matching is applied — a paraphrase is rejected.
"""

from __future__ import annotations

import unicodedata

_QUOTES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "«": '"', "»": '"', "‹": "'", "›": "'",
    "–": "-", "—": "-", "−": "-",
}


def normalize_for_grounding(text: str) -> str:
    text = unicodedata.normalize("NFKC", text or "")
    text = "".join(_QUOTES.get(ch, ch) for ch in text)
    # unify line endings, then collapse every whitespace run to one space
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = " ".join(text.split())
    return text.casefold()


def evidence_span_is_grounded(span: str, source: str) -> bool:
    """True iff ``span`` appears verbatim (after safe normalization) in
    ``source``. An empty or whitespace-only span is never grounded."""
    norm_span = normalize_for_grounding(span)
    if not norm_span:
        return False
    return norm_span in normalize_for_grounding(source)


def validate_grounding(items, masked_text):
    """Split interpreted items into (grounded, rejected) against the masked
    text the interpreter read. Ungrounded items — empty OR invented/paraphrased
    spans — are rejected before anything can become memory."""
    grounded, rejected = [], []
    for item in items:
        if evidence_span_is_grounded(getattr(item, "evidence_span", ""), masked_text):
            grounded.append(item)
        else:
            rejected.append(item)
    return grounded, rejected
