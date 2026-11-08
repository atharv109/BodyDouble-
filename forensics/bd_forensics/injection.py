"""Text from the cloned disk that reaches any model.

Guardrail (PRD "Guardrails in code"): every excerpt is truncated to
EXCERPT_MAX_CHARS and wrapped in <evidence> tags so the model reads it as
data. F13 adds the pre-scan for text that addresses an AI; matches become a
finding and are never followed.
"""
from __future__ import annotations

from contracts import agent as contracts_agent


def _escape(text: str) -> str:
    """Neutralize the body so disk text can never close the wrapper and
    pose as agent-facing instructions (& first, so the escapes themselves
    cannot be re-escaped from inside)."""
    return text.replace("&", "&amp;").replace("<", "&lt;")


def wrap_excerpt(label: str, text: str, max_chars: int | None = None) -> str:
    """Truncate and wrap disk text as quoted evidence, never instructions."""
    limit = contracts_agent.EXCERPT_MAX_CHARS if max_chars is None else max_chars
    body = _escape(text[:limit])
    note = f"\n... [truncated at {limit} chars]" if len(text) > limit else ""
    safe_label = str(label).replace('"', "&quot;")
    return f'<evidence source="{safe_label}">\n{body}{note}\n</evidence>'
