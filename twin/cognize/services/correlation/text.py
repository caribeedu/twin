"""Text helpers for episode cognition briefs (no semantics, just excerpts)."""

from __future__ import annotations

import re

_PREFIX_RE = re.compile(
    r"^(?:GitHub\s+pull\s+request\s+\S+:\s*|"
    r"Commit\s+[0-9a-f]+\s+in\s+\S+\s+by\s+[^:]+:\s*)",
    re.I,
)
_META_LINE_RE = re.compile(
    r"^(?:state:\s|This is the FINAL, merged state)",
    re.I,
)
_WS_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w\s]+", re.UNICODE)


def rich_excerpt(content: str, *, limit: int = 700) -> str:
    """Return a denser excerpt than the first headline alone.

    Keeps the title/subject and following body; drops connector boilerplate
    (``state: MERGED``, ``Commit abc in repo by …:``). Used by amygdala briefs
    and reflect quotes — never invents meaning.
    """
    raw = (content or "").strip()
    if not raw:
        return ""
    kept: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped:
            if kept and kept[-1] != "":
                kept.append("")
            continue
        if _META_LINE_RE.match(stripped):
            continue
        cleaned = _PREFIX_RE.sub("", stripped).strip() or stripped
        kept.append(cleaned)
    # Collapse blank runs; keep paragraph breaks as single newlines for the model.
    paragraphs = [p.strip() for p in "\n".join(kept).split("\n\n") if p.strip()]
    text = "\n".join(paragraphs)
    text = _WS_RE.sub(" ", text.replace("\n", " · ")).strip()
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return text


def normalize_for_compare(text: str) -> str:
    """Lowercase, strip punctuation/boilerplate prefixes, collapse whitespace."""
    t = _PREFIX_RE.sub("", text or "")
    t = _NON_WORD_RE.sub(" ", t.lower())
    return _WS_RE.sub(" ", t).strip()


def texts_diverge(a: str, b: str, *, max_jaccard: float = 0.55) -> bool:
    """True when two excerpts are *not* near-paraphrases of each other.

    Near-duplicate / strong containment → False (structural tautology). Distinct
    token sets → True (worth asking the reflect model about intent shift).
    """
    na, nb = normalize_for_compare(a), normalize_for_compare(b)
    if not na or not nb:
        return False
    if na == nb:
        return False
    shorter, longer = (na, nb) if len(na) <= len(nb) else (nb, na)
    if shorter in longer and len(shorter) >= 0.7 * len(longer):
        return False
    wa, wb = set(na.split()), set(nb.split())
    if not wa or not wb:
        return False
    jaccard = len(wa & wb) / len(wa | wb)
    return jaccard < max_jaccard
