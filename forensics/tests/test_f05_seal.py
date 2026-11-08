"""F5: seal checks in the twin agent.

Done when: both checks pass and are reported (SealStatus in the
TwinRegisterRequest); the agent refuses to pull jobs if either fails.
"""
from __future__ import annotations

import asyncio

from contracts.models import SealStatus, ToolCall, TwinRegisterRequest, TwinRegisterResponse
from contracts.models import ToolName, ToolResult

from bd_forensics.seal import check_disk_read_only, internet_egress_probe, seal_status
from bd_forensics.twin import TwinAgent

RO_MOUNTS = (
    "/dev/vda1 /boot ext4 ro,relatime 0 0\n"
    "/dev/vdb /mnt/disk ext4 ro,relatime 0 0\n"
)
RW_MOUNTS = "/dev/vdb /mnt/disk ext4 rw,relatime 0 0\n"


class FakeControlPlane:
    """Records calls; serves queued jobs then no more, so the loop ends."""

    def __init__(self, jobs: list[ToolCall] | None = None) -> None:
        self.registrations: list[TwinRegisterRequest] = []
        self.pulls = 0
        self.heartbeats = 0
        self.results: list[ToolResult] = []
        self.jobs = list(jobs or [])

    async def register(self, req: TwinRegisterRequest) -> TwinRegisterResponse:
        self.registrations.append(req)
        return TwinRegisterResponse(session_key="sess-1")

    async def next_job(self, session_key: str) -> ToolCall | None:
        self.pulls += 1
        return self.jobs.pop(0) if self.jobs else None

    async def post_result(self, job_id: str, result: ToolResult, session_key: str) -> None:
        self.results.append(result)

    async def heartbeat(self, session_key: str) -> None:
        self.heartbeats += 1


def agent(cp: FakeControlPlane, seal, seal_calls: list[SealStatus] | None = None) -> TwinAgent:
    """Build a TwinAgent whose seal_fn returns `seal`, or each entry of
    seal_calls in turn (register check, then one per loop iteration;
    the last entry repeats)."""
    if seal_calls is None:
        def seal_fn(mount_point):
            return seal
    else:
        queue = list(seal_calls)

        def seal_fn(mount_point):
            return queue.pop(0) if queue else seal_calls[-1]

    return TwinAgent(
        control_plane=cp,
        case_id="case-1",
        token="one-time-token",
        vpc_ip="10.10.0.11",
        seal_fn=seal_fn,
    )


# ---------------------------------------------------------------- seal logic
def test_disk_read_only_passes_on_ro_mount() -> None:
    ok, raw = check_disk_read_only("/mnt/disk", RO_MOUNTS)
    assert ok and "/dev/vdb" in raw


def test_disk_read_only_fails_on_rw_mount() -> None:
    ok, raw = check_disk_read_only("/mnt/disk", RW_MOUNTS)
    assert not ok and "rw" in raw


def test_disk_read_only_fails_when_mount_missing() -> None:
    ok, raw = check_disk_read_only("/mnt/disk", "")
    assert not ok and "not found" in raw


def test_disk_read_only_fails_on_rw_submount() -> None:
    """A stacked rw mount under the disk must fail the check (fail closed)."""
    stacked = RO_MOUNTS + "/dev/vdb2 /mnt/disk/var ext4 rw,relatime 0 0\n"
    ok, raw = check_disk_read_only("/mnt/disk", stacked)
    assert not ok and "/mnt/disk/var" in raw


def test_disk_read_only_parses_mountinfo_too() -> None:
    mountinfo = (
        "22 92 0:40 / /mnt/disk ro,relatime - ext4 /dev/vdb rw\n"
        "23 22 0:41 / /mnt/disk/home ro,relatime - ext4 /dev/vdb2 rw\n"
    )
    ok, raw = check_disk_read_only("/mnt/disk", mountinfo)
    assert ok and "/mnt/disk/home" in raw


def test_egress_blocked_when_all_probes_fail() -> None:
    blocked, raw = internet_egress_probe(targets=[("203.0.113.1", 53)], timeout_s=0.01)
    assert blocked and "failed" in raw


def test_egress_open_when_a_probe_connects() -> None:
    import socket

    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        blocked, raw = internet_egress_probe(targets=[("127.0.0.1", port)], timeout_s=2.0)
    assert not blocked and "CONNECTED" in raw


def test_seal_status_reports_both_checks() -> None:
    s = seal_status(mounts_text=RO_MOUNTS, egress=(True, "tcp 1.1.1.1:53 failed: timeout"))
    assert isinstance(s, SealStatus)
    assert s.disk_read_only and s.egress_blocked and s.sealed
    assert s.detail["egress_blocked"].startswith("tcp ")
    assert s.model_dump()["detail"]["disk_read_only"].startswith("/dev/vdb")


# ---------------------------------------------------------------- agent wiring
def test_agent_registers_with_seal_status() -> None:
    cp = FakeControlPlane()
    sealed = seal_status(mounts_text=RO_MOUNTS, egress=(True, "all probes failed"))
    asyncio.run(agent(cp, sealed).run())
    assert len(cp.registrations) == 1
    req = cp.registrations[0]
    assert req.case_id == "case-1" and req.token == "one-time-token"
    assert isinstance(req.seal, SealStatus) and req.seal.sealed


def test_agent_pulls_jobs_when_sealed() -> None:
    cp = FakeControlPlane()
    sealed = seal_status(mounts_text=RO_MOUNTS, egress=(True, "all probes failed"))
    asyncio.run(agent(cp, sealed).run())
    assert cp.pulls == 1  # registered, sealed, pulled once (None -> idle)


def test_agent_refuses_jobs_when_disk_is_writable() -> None:
    cp = FakeControlPlane()
    unsealed = SealStatus(
        disk_read_only=False,
        egress_blocked=True,
        detail={"disk_read_only": RW_MOUNTS, "egress_blocked": "all probes failed"},
    )
    asyncio.run(agent(cp, unsealed).run())
    assert cp.pulls == 0, "unsealed twin must never pull jobs"
    assert len(cp.registrations) == 1  # still registers, so the failure is visible


def test_agent_refuses_jobs_when_egress_open() -> None:
    cp = FakeControlPlane()
    unsealed = SealStatus(
        disk_read_only=True,
        egress_blocked=False,
        detail={"disk_read_only": RO_MOUNTS.splitlines()[-1], "egress_blocked": "CONNECTED"},
    )
    asyncio.run(agent(cp, unsealed).run())
    assert cp.pulls == 0


def _job(n: int) -> ToolCall:
    return ToolCall(
        job_id=f"job-{n}", case_id="case-1", tool=ToolName.os_facts, args={}
    )


def _tool(job: ToolCall) -> ToolResult:
    return ToolResult(
        job_id=job.job_id, code="print('x')", stdout="x", stderr="",
        exit_code=0, duration_ms=1,
    )


def test_agent_stops_when_seal_breaks_mid_run() -> None:
    """The seal is re-verified per job: a twin that loses isolation mid-run
    refuses further work instead of failing open."""
    cp = FakeControlPlane(jobs=[_job(1), _job(2)])
    sealed = SealStatus(
        disk_read_only=True, egress_blocked=True, detail={"d": "ro", "e": "blocked"}
    )
    broken = SealStatus(
        disk_read_only=False, egress_blocked=True, detail={"d": "rw!", "e": "blocked"}
    )
    a = agent(cp, sealed, seal_calls=[sealed, sealed, broken])
    a.tool_fn = _tool
    asyncio.run(a.run())
    assert cp.pulls == 1, "must not pull the next job once the seal breaks"
    assert len(cp.results) == 1


def test_agent_heartbeats_while_polling() -> None:
    cp = FakeControlPlane()
    sealed = SealStatus(
        disk_read_only=True, egress_blocked=True, detail={"d": "ro", "e": "blocked"}
    )
    asyncio.run(agent(cp, sealed).run())
    assert cp.heartbeats >= 1
