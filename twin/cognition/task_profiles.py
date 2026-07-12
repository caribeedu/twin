"""Task-aware context pack profiles.

Every profile preserves the same firewall and evidence guarantees; what
changes is section ordering and token allocation — an architecture pack
leads with prior decisions and rejected alternatives, a coding pack leads
with active project context and conventions.

Weights are fractions of the memory budget (what remains after the judgment
share); sections render in declaration order.
"""

from __future__ import annotations

from dataclasses import dataclass, field

DECISIONS = ("decision",)
CONSTRAINTS = ("constraint",)
TASKS = ("task",)
PREFERENCES = ("preference",)
FACTS = ("fact", "event", "relationship", "communication_act")
BELIEFS = ("belief", "procedure")


@dataclass
class TaskProfileSpec:
    name: str
    # (section header, memory types, budget share)
    sections: list[tuple[str, tuple[str, ...], float]]
    judgment_share: float = 1 / 3   # max fraction of the budget for judgment
    evidence_hits: int = 3          # verbatim quotes for the top-N hits
    description: str = ""
    keywords: tuple[str, ...] = field(default_factory=tuple)  # inference hints


PROFILES: dict[str, TaskProfileSpec] = {
    "general": TaskProfileSpec(
        name="general",
        description="balanced default",
        sections=[
            ("Decisions", DECISIONS, 0.30),
            ("Constraints", CONSTRAINTS, 0.15),
            ("Open tasks", TASKS, 0.15),
            ("Preferences", PREFERENCES, 0.15),
            ("Facts & events", FACTS + BELIEFS, 0.25),
        ],
    ),
    "coding": TaskProfileSpec(
        name="coding",
        description="active project context, conventions, constraints, risks",
        keywords=("implement", "implementar", "código", "code", "bug fix",
                  "refactor", "função", "function", "endpoint", "test", "teste"),
        sections=[
            ("Active project context", FACTS, 0.25),
            ("Implementation constraints", CONSTRAINTS, 0.20),
            ("Conventions & preferences", PREFERENCES, 0.20),
            ("Relevant decisions", DECISIONS, 0.25),
            ("Known risks & procedures", BELIEFS, 0.05),
            ("Open tasks", TASKS, 0.05),
        ],
    ),
    "architecture": TaskProfileSpec(
        name="architecture",
        description="prior decisions, rejected alternatives, constraints, judgment",
        keywords=("arquitetura", "architecture", "rfc", "adr", "design",
                  "trade-off", "tradeoff", "proposta", "proposal"),
        judgment_share=0.4,
        sections=[
            ("Prior decisions & rejected alternatives", DECISIONS, 0.40),
            ("Constraints", CONSTRAINTS, 0.25),
            ("Open questions & tasks", TASKS, 0.10),
            ("Beliefs & procedures", BELIEFS, 0.10),
            ("Facts & events", FACTS, 0.10),
            ("Preferences", PREFERENCES, 0.05),
        ],
    ),
    "debugging": TaskProfileSpec(
        name="debugging",
        description="known risks, recent events, constraints, procedures",
        keywords=("bug", "erro", "error", "stacktrace", "exception", "falha",
                  "failure", "investigar", "investigate", "debug", "incidente",
                  "incident"),
        judgment_share=0.15,
        sections=[
            ("Recent events & facts", FACTS, 0.35),
            ("Known procedures & beliefs", BELIEFS, 0.20),
            ("Constraints", CONSTRAINTS, 0.15),
            ("Relevant decisions", DECISIONS, 0.20),
            ("Open tasks", TASKS, 0.10),
        ],
    ),
    "writing": TaskProfileSpec(
        name="writing",
        description="communication style, facts, decisions worth citing",
        keywords=("escrever", "write", "documento", "document", "post", "email",
                  "e-mail", "texto", "artigo", "article", "resumo", "summary"),
        judgment_share=0.45,
        sections=[
            ("Facts & events", FACTS, 0.35),
            ("Decisions worth citing", DECISIONS, 0.30),
            ("Preferences", PREFERENCES, 0.20),
            ("Constraints", CONSTRAINTS, 0.15),
        ],
    ),
    "planning": TaskProfileSpec(
        name="planning",
        description="open tasks, goals, decisions, constraints",
        keywords=("planejar", "plan", "roadmap", "sprint", "priorizar",
                  "prioritize", "estimar", "estimate", "milestones"),
        sections=[
            ("Open tasks", TASKS, 0.35),
            ("Decisions", DECISIONS, 0.25),
            ("Constraints", CONSTRAINTS, 0.15),
            ("Facts & events", FACTS, 0.15),
            ("Beliefs & procedures", BELIEFS, 0.10),
        ],
    ),
    "review": TaskProfileSpec(
        name="review",
        description="constraints, conventions, decisions the change must respect",
        keywords=("revisar", "review", "pr", "pull request", "aprovar",
                  "approve", "code review"),
        judgment_share=0.25,
        sections=[
            ("Constraints", CONSTRAINTS, 0.30),
            ("Conventions & preferences", PREFERENCES, 0.25),
            ("Relevant decisions", DECISIONS, 0.30),
            ("Facts & events", FACTS, 0.15),
        ],
    ),
    "meeting_prep": TaskProfileSpec(
        name="meeting_prep",
        description="open tasks, recent decisions, open questions, people",
        keywords=("reunião", "meeting", "1:1", "pauta", "agenda", "sync",
                  "preparar", "prepare", "call"),
        judgment_share=0.15,
        sections=[
            ("Open tasks & commitments", TASKS, 0.35),
            ("Recent decisions", DECISIONS, 0.30),
            ("Facts & events", FACTS, 0.25),
            ("Constraints", CONSTRAINTS, 0.10),
        ],
    ),
}


def get_profile(name: str) -> TaskProfileSpec:
    return PROFILES.get(name, PROFILES["general"])


def infer_task_profile(text: str) -> tuple[str, float]:
    """Cheap keyword inference. Returns (profile_name, confidence 0..1)."""
    lowered = text.lower()
    best, hits = "general", 0
    for spec in PROFILES.values():
        n = sum(1 for kw in spec.keywords if kw in lowered)
        if n > hits:
            best, hits = spec.name, n
    confidence = min(1.0, hits / 2) if hits else 0.0
    return best, confidence
