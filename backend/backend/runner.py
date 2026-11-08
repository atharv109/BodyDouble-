"""TwinStepRunner: contracts.agent.StepRunner over the twin channel — queue
a ToolCall to the twin, await the ToolResult it posts back."""
from __future__ import annotations

import asyncio

from contracts.models import ToolCall, ToolResult


class TwinStepRunner:
    """One runner per investigation. `run` blocks until the twin returns the
    result for this job (twin_job_poll window on the twin side) or the job
    times out (settings.job_timeout_s)."""

    def __init__(self, channel, settings):
        self._channel = channel
        self._settings = settings

    async def run(self, call: ToolCall) -> ToolResult:
        fut = self._channel.enqueue(call)
        return await asyncio.wait_for(fut, timeout=self._settings.job_timeout_s)
