"""Domain Firewall — decides whether a memory may be injected into a given
target context. Policies are declarative YAML; evaluation is first-match-wins
with a hard default-deny for sensitive domains.

A memory passes only if it clears ALL of:
  status gate + temporal validity + confidence floor + policy rules.
Every block is logged (auditable, per the risk section of the project doc).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import yaml

from .config import SENSITIVITY_ORDER
from .db import Database
from .models import MemoryItem

SENSITIVE_DOMAINS = {"relationship", "family", "health", "finance", "emotional", "legal"}


@dataclass
class Verdict:
    allowed: bool
    rule: str
    reason: str
    requires_permission: bool = False


@dataclass
class Rule:
    name: str
    action: str  # allow | block | require_permission
    memory_domains: Optional[list[str]] = None
    target_domains: Optional[list[str]] = None
    max_sensitivity: Optional[str] = None
    min_confidence: Optional[float] = None

    def matches(self, mem: MemoryItem, target_domain: str) -> bool:
        if self.memory_domains and mem.domain not in self.memory_domains:
            return False
        if self.target_domains and target_domain not in self.target_domains:
            return False
        if self.max_sensitivity is not None:
            if SENSITIVITY_ORDER.index(mem.sensitivity.value) > SENSITIVITY_ORDER.index(self.max_sensitivity):
                return True  # rule matches memories ABOVE the allowed sensitivity
            return False
        return True


class Firewall:
    def __init__(self, policies_path: Path | str, db: Optional[Database] = None):
        self.db = db
        data = yaml.safe_load(Path(policies_path).read_text(encoding="utf-8")) or {}
        self.default_action: str = data.get("default_action", "allow")
        self.min_confidence: float = float(data.get("min_confidence", 0.0))
        self.allowed_statuses: list[str] = data.get(
            "allowed_statuses", ["confirmed", "candidate"]
        )
        self.rules: list[Rule] = []
        for raw in data.get("rules", []):
            match = raw.get("if", {})
            self.rules.append(Rule(
                name=raw.get("name", "unnamed"),
                action=raw.get("action", "block"),
                memory_domains=match.get("memory_domain"),
                target_domains=match.get("target_domain"),
                max_sensitivity=match.get("sensitivity_above"),
                min_confidence=match.get("confidence_below"),
            ))

    def evaluate(self, mem: MemoryItem, target_domain: str, as_of: Optional[str] = None) -> Verdict:
        # hard gates first
        if mem.status.value not in self.allowed_statuses:
            return self._log(mem, target_domain, Verdict(False, "status_gate", f"status={mem.status.value}"))
        if mem.valid_until and as_of and mem.valid_until < as_of:
            return self._log(mem, target_domain, Verdict(False, "temporal_gate", "memory expired"))
        if mem.confidence < self.min_confidence:
            return self._log(mem, target_domain, Verdict(False, "confidence_gate", f"confidence={mem.confidence:.2f}"))

        for rule in self.rules:
            if rule.min_confidence is not None and mem.confidence < rule.min_confidence and rule.matches(mem, target_domain):
                return self._log(mem, target_domain, Verdict(rule.action == "allow", rule.name, "confidence rule", rule.action == "require_permission"))
            if rule.min_confidence is None and rule.matches(mem, target_domain):
                if rule.action == "allow":
                    return Verdict(True, rule.name, "explicit allow")
                if rule.action == "require_permission":
                    return self._log(mem, target_domain, Verdict(False, rule.name, "requires explicit user permission", True))
                return self._log(mem, target_domain, Verdict(False, rule.name, "blocked by policy"))

        # hard default-deny for sensitive personal domains crossing into others
        if mem.domain in SENSITIVE_DOMAINS and target_domain != mem.domain:
            return self._log(mem, target_domain, Verdict(False, "sensitive_default_deny", f"{mem.domain} → {target_domain}"))

        if self.default_action == "allow":
            return Verdict(True, "default", "default allow")
        return self._log(mem, target_domain, Verdict(False, "default", "default deny"))

    def _log(self, mem: MemoryItem, target_domain: str, verdict: Verdict) -> Verdict:
        if self.db is not None and not verdict.allowed:
            self.db.log_firewall(mem.id, target_domain, verdict.rule, "block")
        return verdict
