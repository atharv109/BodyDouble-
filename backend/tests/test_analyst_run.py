from __future__ import annotations

import asyncio

import pytest
import httpx

from backend.db import CaseRow, StepRow
from contracts.models import CaseState, StepKind, ToolName


async def _case(client, human):
    r = await client.post("/cases", headers=human, json={
        "instance_id": "inst-shop-prod", "reason": "analyst test"})
    assert r.status_code == 201
    return r.json()


async def test_analyst_run_requires_human_and_sealed_live_case(client, state, human):
    case = await _case(client, human)
    case_id = case["id"]
    client.cookies.clear()
    assert (await client.post(f"/cases/{case_id}/analyst/run",
                              json={"tool": "os_facts", "args": {}})).status_code == 401
    r = await client.post(f"/cases/{case_id}/analyst/run", headers=human,
                          json={"tool": "os_facts", "args": {}})
    assert r.status_code == 200, r.text
    assert "Debian" in r.json()["result"]["stdout"]
    with state.sf() as session:
        saved = session.get(StepRow, r.json()["step"]["id"])
        assert saved.exit_code == 0 and "Debian" in saved.stdout
    assert state.log.entries(case_id)[-1].event == "human_tool_run"


@pytest.mark.parametrize("payload", [
    {"tool": "os.system", "args": {}},
    {"tool": "extract", "args": {"path": "../../etc/passwd"}},
    {"tool": "custom_script", "args": {"code": "x" * 17000}},
])
async def test_analyst_run_rejects_unknown_or_unsafe_tools(client, human, payload):
    case = await _case(client, human)
    response = await client.post(f"/cases/{case['id']}/analyst/run",
                                 headers=human, json=payload)
    assert response.status_code == 422


async def test_analyst_run_rejects_terminal_cases(client, state, human):
    case = await _case(client, human)
    row = case["id"]
    # This endpoint's state gate is the unit under test; closing normally is
    # only legal after reporting and introduces an unrelated background race.
    with state.sf() as session:
        saved = session.get(CaseRow, row)
        saved.state = CaseState.closed.value
        session.commit()
    response = await client.post(f"/cases/{row}/analyst/run", headers=human,
                                 json={"tool": "os_facts", "args": {}})
    assert response.status_code == 409


async def test_analyst_run_allocates_after_sparse_step_ids(client, state, human):
    case = await _case(client, human)
    with state.sf() as session:
        for seq in (4, 5, 6):
            session.add(StepRow(
                id=f"{case['id']}-step-{seq:03d}", case_id=case["id"], seq=seq,
                kind=StepKind.triage.value, tool=ToolName.os_facts.value,
                args={}, code="", stdout="", stderr="", exit_code=0,
                duration_ms=0,
            ))
        session.commit()
    response = await client.post(f"/cases/{case['id']}/analyst/run", headers=human,
                                 json={"tool": "os_facts", "args": {}})
    assert response.status_code == 200, response.text
    assert response.json()["step"]["id"] == f"{case['id']}-step-007"


async def test_startup_recovers_live_fake_twin_for_analyst_run(tmp_path):
    from backend.config import test_settings
    from backend.state import build_state

    url = f"sqlite:///{(tmp_path / 'restart.db').as_posix()}"
    settings = test_settings(url)
    state = build_state(settings)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=state.app),
                                base_url="http://t") as client:
        auth = await client.post("/auth/session", json={"operator": "operator"})
        headers = {"X-Human-Session": auth.json()["session_token"]}
        opened = await client.post("/cases", headers=headers, json={
            "instance_id": "inst-shop-prod", "reason": "restart recovery test"})
        assert opened.status_code == 201, opened.text
        case_id = opened.json()["id"]
    for task in state.fake_twin_tasks.values():
        task.cancel()
    await asyncio.gather(*state.fake_twin_tasks.values(), return_exceptions=True)
    state.fake_twin_tasks.clear()
    state.channel.cleanup_case(case_id)
    state.close()

    restarted = build_state(test_settings(url))
    try:
        for callback in restarted.app.router.on_startup:
            await callback()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=restarted.app),
                                    base_url="http://t") as client:
            auth = await client.post("/auth/session", json={"operator": "operator"})
            headers = {"X-Human-Session": auth.json()["session_token"]}
            response = await client.post(
                f"/cases/{case_id}/analyst/run", headers=headers,
                json={"tool": "os_facts", "args": {}})
            assert response.status_code == 200, response.text
            assert "Debian" in response.json()["result"]["stdout"]
    finally:
        for task in restarted.fake_twin_tasks.values():
            task.cancel()
        await asyncio.gather(*restarted.fake_twin_tasks.values(), return_exceptions=True)
        for callback in restarted.app.router.on_shutdown:
            await callback()
        restarted.close()
