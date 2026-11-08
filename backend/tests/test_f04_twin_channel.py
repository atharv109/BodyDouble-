"""F4: the twin channel. POST /twin/register (one-time token, VPC source
only), POST /twin/heartbeat, GET /twin/jobs/next, POST /twin/jobs/{id}/result,
all with X-Twin-Session; plus the StepRunner and CaseRecorder from
contracts/agent.py. Done when: heartbeat received from the VPC address; a
request from a non-VPC address or a reused token is rejected."""
from __future__ import annotations

import pytest

from contracts.models import (
    CaseState,
    Evidence,
    Finding,
    SealStatus,
    Severity,
    Step,
    StepKind,
    ToolCall,
    ToolName,
)
from contracts.vultr import FakeVultr

from backend.db import EvidenceRow, FindingRow, StepRow
from conftest import make_src_client, open_env

PUBLIC_IP = "203.0.113.99"   # off-VPC source, RFC-5737 documentation address
VPC_IP = "10.1.96.3"         # inside the first case's VPC (10.1.96.0/24)


async def _open_case(client, headers):
    r = await client.post("/cases", headers=headers, json={
        "instance_id": FakeVultr.SHOP_PROD, "reason": "cpu pegged"})
    assert r.status_code == 201, r.text
    return r.json()


def _twin_session(state):
    """The one live twin session (the in-process twin registered on boot)."""
    assert len(state.channel.sessions) == 1
    return next(iter(state.channel.sessions.values()))


def _seal_body(sealed: bool = True) -> dict:
    return {"disk_read_only": sealed, "egress_blocked": sealed,
            "detail": {"disk_read_only": "cloned disk mounted read-only",
                       "egress_blocked": "egress default DROP; VPC only"}}


# --------------------------------------------------------------- heartbeat
async def test_heartbeat_received_from_vpc_address(client, app, state, human):
    await _open_case(client, human)
    sess = _twin_session(state)
    async with make_src_client(app, sess.vpc_ip) as c:
        r = await c.post("/twin/heartbeat", headers={"X-Twin-Session": sess.key})
    assert r.status_code == 204


async def test_heartbeat_from_non_vpc_address_rejected(client, app, state, human):
    await _open_case(client, human)
    sess = _twin_session(state)
    async with make_src_client(app, PUBLIC_IP) as c:
        r = await c.post("/twin/heartbeat", headers={"X-Twin-Session": sess.key})
    assert r.status_code == 403


async def test_heartbeat_requires_valid_session(client, app, state, human):
    await _open_case(client, human)
    sess = _twin_session(state)
    async with make_src_client(app, sess.vpc_ip) as c:
        r1 = await c.post("/twin/heartbeat")  # no X-Twin-Session at all
        r2 = await c.post("/twin/heartbeat", headers={"X-Twin-Session": "twinsess-bogus"})
    assert r1.status_code == 401
    assert r2.status_code == 401


# --------------------------------------------------------------- register
async def test_register_rejects_non_vpc_source_and_keeps_token(tmp_path):
    async with open_env(tmp_path, spawn_fake_twin=False,
                        register_timeout_s=0.1) as (st, client):
        case = await _open_case(client, {})  # no twin registers -> case fails
        assert case["state"] == CaseState.failed.value
        token = st.service.row(case["id"]).reg_token
        assert token  # untouched by the failed run

        async with make_src_client(st.app, PUBLIC_IP) as c:
            r = await c.post("/twin/register", json={
                "case_id": case["id"], "token": token,
                "vpc_ip": VPC_IP, "seal": _seal_body()})
        assert r.status_code == 403  # registration must come from the VPC
        # and the rejection did not burn the one-time token
        assert st.service.row(case["id"]).reg_token == token


async def test_register_token_rejected_on_reuse(tmp_path):
    async with open_env(tmp_path, spawn_fake_twin=False,
                        register_timeout_s=0.1) as (st, client):
        case = await _open_case(client, {})
        token = st.service.row(case["id"]).reg_token
        async with make_src_client(st.app, VPC_IP) as c:
            first = await c.post("/twin/register", json={
                "case_id": case["id"], "token": token,
                "vpc_ip": VPC_IP, "seal": _seal_body()})
            second = await c.post("/twin/register", json={
                "case_id": case["id"], "token": token,
                "vpc_ip": VPC_IP, "seal": _seal_body()})
        assert first.status_code == 200 and first.json()["session_key"]
        assert second.status_code == 403  # the token is one-time


async def test_register_rejects_wrong_token(tmp_path):
    async with open_env(tmp_path, spawn_fake_twin=False,
                        register_timeout_s=0.1) as (st, client):
        case = await _open_case(client, {})
        async with make_src_client(st.app, VPC_IP) as c:
            r = await c.post("/twin/register", json={
                "case_id": case["id"], "token": "twreg-not-the-token",
                "vpc_ip": VPC_IP, "seal": _seal_body()})
        assert r.status_code == 403


# --------------------------------------------------------------- jobs
async def test_jobs_next_returns_204_when_no_jobs(client, app, state, human):
    await _open_case(client, human)
    sess = _twin_session(state)
    async with make_src_client(app, sess.vpc_ip) as c:
        r = await c.get("/twin/jobs/next", headers={"X-Twin-Session": sess.key})
    assert r.status_code == 204


async def test_jobs_next_gone_once_the_case_failed(tmp_path):
    async with open_env(tmp_path, spawn_fake_twin=False,
                        register_timeout_s=0.1) as (st, client):
        case = await _open_case(client, {})
        token = st.service.row(case["id"]).reg_token
        async with make_src_client(st.app, VPC_IP) as c:
            reg = await c.post("/twin/register", json={
                "case_id": case["id"], "token": token,
                "vpc_ip": VPC_IP, "seal": _seal_body()})
            r = await c.get("/twin/jobs/next",
                            headers={"X-Twin-Session": reg.json()["session_key"]})
        assert reg.status_code == 200
        assert r.status_code == 410  # the case is over; the twin stands down


async def test_jobs_result_rejects_unknown_job(client, app, state, human):
    await _open_case(client, human)
    sess = _twin_session(state)
    async with make_src_client(app, sess.vpc_ip) as c:
        r = await c.post("/twin/jobs/job-nope/result",
                         headers={"X-Twin-Session": sess.key},
                         json={"job_id": "job-nope", "code": "x", "stdout": "",
                               "stderr": "", "exit_code": 0, "duration_ms": 0})
    assert r.status_code == 404


# --------------------------------------------------------------- seal flow
async def test_case_reaches_sealed_with_seal_check_events(client, state, human):
    case = await _open_case(client, human)
    assert case["state"] == CaseState.sealed.value

    entries = state.log.entries(case["id"])
    states = [e.payload["to_state"] for e in entries if e.event == "state_changed"]
    assert states == [CaseState.opened.value, CaseState.snapshotting.value,
                      CaseState.restoring.value, CaseState.sealed.value]
    checks = [e for e in entries if e.event == "seal_check"]
    assert {e.payload["check"] for e in checks} == {"disk_read_only", "egress_blocked"}
    assert all(e.payload["passed"] for e in checks)
    assert all(e.payload["output"] for e in checks)  # raw output shown on screen

    row = state.service.row(case["id"])
    assert row.twin_internal_ip == VPC_IP
    assert row.reg_token is None  # consumed by the twin's registration
    assert SealStatus.model_validate(row.seal).sealed


# --------------------------------------------------------------- runner + recorder
async def test_step_runner_round_trip_through_the_twin(client, state, human):
    from backend.db import JobRow
    from backend.runner import TwinStepRunner

    case = await _open_case(client, human)
    runner = TwinStepRunner(state.channel, state.settings)
    call = ToolCall(job_id=f"{case['id']}-job-001", case_id=case["id"],
                    tool=ToolName.os_facts, args={})
    res = await runner.run(call)
    assert res.job_id == call.job_id
    assert res.exit_code == 0 and "fake twin" in res.stdout
    with state.sf() as s:
        job = s.get(JobRow, call.job_id)
    assert job is not None and job.result is not None
    assert job.result["exit_code"] == 0


async def test_recorder_persists_steps_evidence_findings_and_logs(client, state, human):
    from backend.recorder import DbCaseRecorder

    case = await _open_case(client, human)
    cid = case["id"]
    rec = DbCaseRecorder(state.sf, state.log)

    step = Step(id=f"{cid}-st-001", case_id=cid, seq=1, kind=StepKind.triage,
                tool=ToolName.os_facts, rationale="OS facts first", code="uname -a")
    await rec.step_started(step)
    await rec.step_finished(step.model_copy(update={
        "stdout": "Linux twin 6.1", "exit_code": 0, "duration_ms": 3}))
    ev = Evidence(id=f"{cid}-ev-002", case_id=cid, step_id=step.id,
                  path="/etc/os-release", sha256="ab" * 32, excerpt='NAME="Ubuntu"')
    await rec.add_evidence(ev)
    await rec.dns_captured(step.id, "c2.example.com", "192.0.2.1", ev.id)
    fd = Finding(id=f"{cid}-fd-001", case_id=cid, title="Cron backdoor",
                 severity=Severity.high, summary="rogot cron entry phones home",
                 evidence_ids=[ev.id])
    await rec.add_finding(fd)

    with state.sf() as s:
        st_row = s.get(StepRow, step.id)
        ev_row = s.get(EvidenceRow, ev.id)
        fd_row = s.get(FindingRow, fd.id)
    assert st_row.exit_code == 0 and st_row.stdout == "Linux twin 6.1"
    assert ev_row.path == "/etc/os-release"
    assert fd_row.severity == Severity.high.value

    names = [e.event for e in state.log.entries(cid)]
    for expected in ("step_started", "step_finished", "dns_captured", "finding_added"):
        assert expected in names
    # every broadcast entry validates against contracts.events (sse_replay asserts payloads)
    state.log.sse_replay(cid)

    # findings citing unknown evidence ids are rejected
    bad = fd.model_copy(update={"id": f"{cid}-fd-002",
                                "evidence_ids": [f"{cid}-ev-nope"]})
    with pytest.raises(ValueError):
        await rec.add_finding(bad)
