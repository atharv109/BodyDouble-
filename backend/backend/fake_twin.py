"""In-process stand-in for the forensics ISO (FakeVultr mode only).

The real ISO boots on the twin, checks in over the VPC with its one-time
token, then long-polls for ToolCalls and posts ToolResults. This loop plays
that role for FakeVultr: it registers with passing seal checks and executes
the real fixed read-only tools against demo/victim. Sandboxed tools never
fall back to host execution when the runtime is unavailable."""
from __future__ import annotations

import asyncio
from pathlib import Path

from contracts.models import SealStatus, ToolName, ToolResult

from bd_forensics.tools import execute

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
            victim = Path(__file__).resolve().parents[2] / "demo" / "victim"
            try:
                result = await asyncio.to_thread(
                    execute, job, str(victim), settings.job_timeout_s
                )
            except (FileNotFoundError, RuntimeError, OSError) as exc:
                if job.tool not in (ToolName.custom_script, ToolName.detonate):
                    raise
                # Sandbox tools must never fall back to host execution.  A
                # missing CLI, daemon, runtime, or image is an explicit result.
                result = ToolResult(
                    job_id=job.job_id, code="# sandbox unavailable",
                    stdout="", stderr=f"sandbox unavailable: {exc}",
                    exit_code=126, duration_ms=0,
                )
            result.job_id = job.job_id
            if result.exit_code != 126:
                result.stdout = "[fake twin] demo/victim\n" + result.stdout
            channel.submit_result(sess, job.job_id, result)
        except TwinChannelError:
            return  # case closed/failed (410) or the session is gone
