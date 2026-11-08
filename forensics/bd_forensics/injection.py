"""Text from the cloned disk that reaches any model.

Guardrail (PRD "Guardrails in code"): every excerpt is truncated to
EXCERPT_MAX_CHARS and wrapped in <evidence> tags so the model reads it as
data. F13 adds the pre-scan for text that addresses an AI; matches become a
finding and are never followed.
"""
from __future__ import annotations

from contracts import agent as contracts_agent


def wrap_excerpt(label: str, text: str, max_chars: int | None = None) -> str:
    """Truncate and wrap disk text as quoted evidence, never instructions."""
    limit = contracts_agent.EXCERPT_MAX_CHARS if max_chars is None else max_chars
    body = text[:limit]
    note = f"\n... [truncated at {limit} chars]" if len(text) > limit else ""
    return f'<evidence source="{label}">\n{body}{note}\n</evidence>'
