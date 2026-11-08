"""Model access: the planner, analyst and reporter all call Vultr Serverless
Inference through the OpenAI-compatible client (contracts.agent.INFERENCE_BASE_URL).

Tests stub the model - never a real key. On the control plane the backend
owns the inference key and constructs OpenAIModel with it.
"""
from __future__ import annotations

import os
from typing import Protocol

from contracts import agent as contracts_agent


class Model(Protocol):
    async def chat(self, messages: list[dict[str, str]]) -> str: ...


class OpenAIModel:
    """Real model client. The key comes from the backend (or env), never from here."""

    def __init__(self, api_key: str, model: str | None = None) -> None:
        from openai import AsyncOpenAI

        self._model = model or os.environ.get("BD_INFERENCE_MODEL", "MODEL_ID")
        self._client = AsyncOpenAI(
            base_url=contracts_agent.INFERENCE_BASE_URL, api_key=api_key
        )
        self.total_tokens = 0

    async def chat(self, messages: list[dict[str, str]]) -> str:
        resp = await self._client.chat.completions.create(
            model=self._model, messages=messages
        )
        usage = getattr(resp, "usage", None)
        self.total_tokens += int(getattr(usage, "total_tokens", 0) or 0)
        content = resp.choices[0].message.content
        assert isinstance(content, str)
        return content
