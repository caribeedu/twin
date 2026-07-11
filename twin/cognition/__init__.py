"""Cognitive Core — turns percepts into memory and memory into context.

- extraction: percepts → candidate memories (local LLM via Ollama by
  default; rule-based heuristic as offline fallback)
- dedupe: duplicate / contradiction detection
- observer: attention — suggests memories for the current task
- context_pack: recall — compact, firewall-filtered context for external LLMs
"""

from .pipeline import ExtractReport, extract_pending, extract_percept

__all__ = ["ExtractReport", "extract_pending", "extract_percept"]
