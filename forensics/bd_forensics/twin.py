"""The twin-side agent (F4/F5): boots on the forensics ISO, checks its own
seal, registers with the control plane over the VPC using the one-time token,
then long-polls for ToolCalls and posts ToolResults.

F5: it refuses to pull jobs unless BOTH seal checks pass. It still registers
when unsealed, so the control plane can show the failed check on screen.
"""
from __future__ import annotations

import logging
from typing import Callable, Protocol

from contracts.models import ToolCall, ToolResult, TwinRegisterRequest, TwinRegisterResponse
from contracts.models import SealStatus

from . import seal as seal_mod

log = logging.getLogger("bd_forensics.twin")


class ControlPlane(Protocol):
    """How the twin talks to the control plane over the VPC (contracts.endpoints)."""

    async def register(self, req: TwinRegisterRequest) -> TwinRegisterResponse: ...
    async def next_job(self, session_key: str) -> ToolCall | None: ...
    async def post_result(self, job_id: str, result: ToolResult, session_key: str) -> None: ...
    async def heartbeat(self, session_key: str) -> None: ...


SealFn = Callable[..., SealStatus]
ToolFn = Callable[[ToolCall], "ToolResult | object"]


class TwinAgent:
    def __init__(
        self,
        control_plane: ControlPlane,
        case_id: str,
        token: str,
        vpc_ip: str,
        mount_point: str = seal_mod.MOUNT_POINT,
        seal_fn: SealFn = seal_mod.seal_status,
        tool_fn: ToolFn | None = None,
    ) -> None:
        self.cp = control_plane
        self.case_id = case_id
        self.token = token
        self.vpc_ip = vpc_ip
        self.mount_point = mount_point
        self.seal_fn = seal_fn
        self.tool_fn = tool_fn
        self.session_key: str | None = None

    async def run(self) -> SealStatus:
        """Register (reporting the seal either way), then pull jobs only if sealed.

        The seal is re-verified before accepting every job: a twin that
        loses isolation mid-run refuses further work instead of failing open.
        """
        s = self.seal_fn(self.mount_point)
        resp = await self.cp.register(
            TwinRegisterRequest(
                case_id=self.case_id, token=self.token, vpc_ip=self.vpc_ip, seal=s
            )
        )
        self.session_key = resp.session_key
        if not s.sealed:
            log.error("seal failed; refusing to pull jobs: %s", s.detail)
            return s
        while True:
            s = self.seal_fn(self.mount_point)
            if not s.sealed:
                log.error("seal broken mid-run; refusing further jobs: %s", s.detail)
                return s
            job = await self.cp.next_job(self.session_key)
            await self.cp.heartbeat(self.session_key)
            if job is None:
                return s
            if self.tool_fn is None:
                raise RuntimeError(f"no tool handler wired for {job.tool}")
            result = self.tool_fn(job)  # toolkit dispatch lands in F6
            if hasattr(result, "__await__"):
                result = await result
            await self.cp.post_result(job.job_id, result, self.session_key)
