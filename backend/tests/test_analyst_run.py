from __future__ import annotations

import pytest

from backend.db import CaseRow, StepRow
from contracts.models import CaseState


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
