"""Real control-plane client for the twin (contracts.endpoints /twin/* routes).

The twin only ever talks to the control plane over the case VPC; the base
URL is passed at boot (kernel cmdline bd.cp=...). Tests use fakes instead.
"""
from __future__ import annotations

import httpx

from contracts.models import ToolCall, ToolResult, TwinRegisterRequest, TwinRegisterResponse


class HttpControlPlane:
    def __init__(self, base_url: str, timeout_s: float = 30.0) -> None:
        self._client = httpx.AsyncClient(base_url=base_url, timeout=timeout_s)

    async def register(self, req: TwinRegisterRequest) -> TwinRegisterResponse:
        r = await self._client.post("/twin/register", json=req.model_dump())
        r.raise_for_status()
        return TwinRegisterResponse.model_validate_json(r.content)

    async def next_job(self, session_key: str) -> ToolCall | None:
        """Long-poll for the next ToolCall; None on 204 (no job in 25 s)."""
        r = await self._client.get(
            "/twin/jobs/next", headers={"X-Twin-Session": session_key}
        )
        if r.status_code == 204:
            return None
        r.raise_for_status()
        return ToolCall.model_validate_json(r.content)

    async def post_result(self, job_id: str, result: ToolResult, session_key: str) -> None:
        r = await self._client.post(
            f"/twin/jobs/{job_id}/result",
            json=result.model_dump(),
            headers={"X-Twin-Session": session_key},
        )
        r.raise_for_status()

    async def heartbeat(self, session_key: str) -> None:
        r = await self._client.post("/twin/heartbeat", headers={"X-Twin-Session": session_key})
        r.raise_for_status()
