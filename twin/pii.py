"""PII detection and masking.

Runs before any text is sent to a cloud LLM. Regex-based on purpose: it is
deterministic, auditable and has zero dependencies. Catches the classes of
data most dangerous to leak from technical/professional sources: emails,
phone numbers, Brazilian documents (CPF/CNPJ), credit cards, and credentials
(API keys, tokens, private keys).
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    ("cpf", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
    ("cnpj", re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("phone", re.compile(r"(?<![\w./-])\+?\d{2}?\s?\(?\d{2,3}\)?[\s.-]?\d{4,5}[\s.-]\d{4}\b")),
    # Credentials — common key formats + generic assignment of secrets.
    ("api_key", re.compile(
        r"\b(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}"
        r"|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})\b"
    )),
    ("secret_assignment", re.compile(
        r"(?i)\b(password|senha|secret|token|api[_-]?key)\s*[:=]\s*\S+"
    )),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
]


@dataclass
class PIIFinding:
    kind: str
    text: str
    start: int
    end: int


def detect(text: str) -> list[PIIFinding]:
    findings: list[PIIFinding] = []
    taken: list[tuple[int, int]] = []
    for kind, pattern in _PATTERNS:
        for m in pattern.finditer(text):
            span = (m.start(), m.end())
            # skip overlaps with an earlier (higher-priority) pattern
            if any(s < span[1] and span[0] < e for s, e in taken):
                continue
            taken.append(span)
            findings.append(PIIFinding(kind=kind, text=m.group(0), start=span[0], end=span[1]))
    findings.sort(key=lambda f: f.start)
    return findings


def mask(text: str) -> tuple[str, list[PIIFinding]]:
    """Replace each finding with a stable placeholder like ``[EMAIL_1]``.
    Returns the masked text and the findings (kept locally, never sent out).
    """
    findings = detect(text)
    counters: dict[str, int] = {}
    out: list[str] = []
    cursor = 0
    for f in findings:
        counters[f.kind] = counters.get(f.kind, 0) + 1
        out.append(text[cursor:f.start])
        out.append(f"[{f.kind.upper()}_{counters[f.kind]}]")
        cursor = f.end
    out.append(text[cursor:])
    return "".join(out), findings
