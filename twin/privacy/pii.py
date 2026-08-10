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
    # Credentials — common key formats + generic assignment of secrets.
    ("jwt", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\b")),
    ("api_key", re.compile(
        r"\b(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}"
        r"|github_pat_[A-Za-z0-9_]{20,}|glpat-[A-Za-z0-9_-]{16,}"
        r"|xox[baprs]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})\b"
    )),
    ("bearer_token", re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/-]{16,}=*")),
    ("secret_assignment", re.compile(
        r"(?i)\b(password|senha|secret|token|api[_-]?key|access[_-]?key|client[_-]?secret)"
        r"\s*[:=]\s*\S+"
    )),
    ("private_key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----")),
    # Brazilian documents / identifiers
    ("cpf", re.compile(r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b")),
    ("cnpj", re.compile(r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b")),
    ("rg", re.compile(r"(?i)\bRG[:\s]*\d{1,2}\.?\d{3}\.?\d{3}-?[0-9Xx]\b")),
    ("cep", re.compile(r"(?<![\w.-])\d{5}-\d{3}\b")),
    # Financial
    ("iban", re.compile(r"\b[A-Z]{2}\d{2}[A-Z0-9]{11,30}\b")),
    ("credit_card", re.compile(r"\b(?:\d[ -]?){13,16}\b")),
    ("pix_random_key", re.compile(
        r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b"
    )),
    # Contact / location
    ("phone", re.compile(r"(?<![\w./-])\+?\d{2}?\s?\(?\d{2,3}\)?[\s.-]?\d{4,5}[\s.-]\d{4}\b")),
    ("street_address", re.compile(
        r"(?i)\b(rua|avenida|av\.|alameda|travessa|rodovia|estrada)\s"
        r"[A-Za-zÀ-ÿ0-9. ]{3,60},?\s*(n[ºo°.]?\s*)?\d{1,5}\b"
    )),
    ("ipv4", re.compile(
        r"\b(?:(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\.){3}(?:25[0-5]|2[0-4]\d|1\d\d|[1-9]?\d)\b"
    )),
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
