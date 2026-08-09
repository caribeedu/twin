"""Cognize availability gate.

Without a chat LLM, Cognize writes nothing. Sense I/O and the Domain Firewall
may still run.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class CognizeHaltReason(str, Enum):
    llm_unreachable = "llm_unreachable"
    llm_misconfigured = "llm_misconfigured"
    heuristic_meaning_requested = "heuristic_meaning_requested"
    extractor_mode_blocks_cognition = "extractor_mode_blocks_cognition"
    echo_not_allowed = "echo_not_allowed"


@dataclass(frozen=True)
class CognizeGateResult:
    ok: bool
    halt_reason: Optional[CognizeHaltReason] = None
    detail: str = ""

    @property
    def halted(self) -> bool:
        return not self.ok


def require_chat_llm(
    *,
    extractor: str = "auto",
    chat_provider: str = "",
    chat_reachable: Optional[bool] = None,
    allow_echo_cognition: bool = False,
) -> CognizeGateResult:
    """Return Ok or Halt before any Cognize cognitive writes.

    ``chat_reachable`` should be probed by the caller (network ping / list
    models). When ``None``, reachability is not checked — only config mode.
    """
    mode = (extractor or "auto").strip().lower()
    if mode == "heuristic":
        return CognizeGateResult(
            ok=False,
            halt_reason=CognizeHaltReason.extractor_mode_blocks_cognition,
            detail="TWIN_EXTRACTOR=heuristic cannot establish cognitive meaning",
        )
    if mode == "echo" and not allow_echo_cognition:
        return CognizeGateResult(
            ok=False,
            halt_reason=CognizeHaltReason.echo_not_allowed,
            detail="echo extractor is a test double; set TWIN_ALLOW_ECHO_COGNITION=1 only in tests",
        )
    if mode in ("", "none", "off"):
        return CognizeGateResult(
            ok=False,
            halt_reason=CognizeHaltReason.llm_misconfigured,
            detail="no chat extractor / LLM configured for Cognize",
        )
    if not (chat_provider or "").strip() and mode in ("auto", "ollama"):
        # auto/ollama still need a provider resolution later; treat empty as misconfigured
        # only when caller explicitly passed empty provider *and* asked us to check.
        pass
    if chat_reachable is False:
        return CognizeGateResult(
            ok=False,
            halt_reason=CognizeHaltReason.llm_unreachable,
            detail="chat LLM unreachable",
        )
    if mode not in ("auto", "ollama", "openai", "openai_compatible", "anthropic",
                    "claude", "gemini", "google", "groq", "openrouter", "lmstudio",
                    "vllm", "echo") and not allow_echo_cognition:
        # Unknown production meaning backends are refuse-closed.
        if mode == "echo":
            return CognizeGateResult(
                ok=False,
                halt_reason=CognizeHaltReason.echo_not_allowed,
                detail="echo not allowed",
            )
    return CognizeGateResult(ok=True)
