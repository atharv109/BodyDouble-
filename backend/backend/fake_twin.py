"""In-process stand-in for the forensics ISO (FakeVultr mode only).

The real ISO boots on the twin, checks in over the VPC with its one-time
token, then long-polls for ToolCalls and posts ToolResults. Until forensics/
is merged this loop plays that role so the control plane's full case flow can
run on FakeVultr: it registers with passing seal checks, then answers every
queued ToolCall with a canned ToolResult until the case is closed or failed
(the channel then raises TwinChannelError and the loop exits)."""
from __future__ import annotations

import asyncio

from contracts.models import SealStatus, ToolResult

from .db import CaseRow
from .twin import TwinChannelError


async def fake_twin_loop(state, case_id: str, token: str, vpc_ip: str) -> None:
    channel = state.channel
    settings = state.settings
    try:
        resp = channel.register(case_id, token, vpc_ip, SealStatus(
            disk_read_only=True,
            egress_blocked=True,
            detail={"disk_read_only": "cloned disk mounted read-only",
                    "egress_blocked": "egress default DROP; VPC only"}),
            client_ip=vpc_ip)
    except TwinChannelError as e:
        channel.notify_seal_failed(case_id, f"registration failed: {e}")
        return
    sess = channel.sessions[resp.session_key]
    while True:
        try:
            with state.sf() as s:
                row = s.get(CaseRow, case_id)
            if row is None:
                return
            channel.heartbeat(sess)
            job = await channel.next_job(sess, row, settings.twin_job_poll_s)
            if job is None:
                continue
            result = ToolResult(
                job_id=job.job_id, code=f"# fake twin stand-in: {job.tool}",
                stdout=f"[fake twin] {job.tool} ok", stderr="", exit_code=0,
                duration_ms=0)
            channel.submit_result(sess, job.job_id, result)
        except TwinChannelError:
            return  # case closed/failed (410) or the session is gone
