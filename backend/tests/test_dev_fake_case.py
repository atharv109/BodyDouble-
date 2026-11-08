from __future__ import annotations

import pytest

from contracts.events import EventName, parse_sse
from contracts.models import ActionKind, ActionStatus


@pytest.mark.asyncio
async def test_dev_fake_case_stops_reported_then_browser_applies_and_closes(
    client, human, state
):
    response = await client.post("/dev/fake-case", headers=human, json={})
    assert response.status_code == 201, response.text
    case = response.json()
    assert case["state"] == "reported"

    detail = (await client.get(f"/cases/{case['id']}", headers=human)).json()
    assert [step["id"] for step in detail["steps"]] == [f"step-{i:02d}" for i in range(1, 8)]
    assert len(detail["findings"]) == 6
    assert len(detail["actions"]) == 4
    assert [action["id"] for action in detail["actions"]] == [f"act-{i}" for i in range(1, 5)]
    assert {action["kind"] for action in detail["actions"]} == {
        kind.value for kind in ActionKind if kind is not ActionKind.manual_plan
    }
    assert all(action["status"] == ActionStatus.proposed.value
               for action in detail["actions"])
    assert state.vultr.instances["inst-shop-prod"].firewall_group_id == "fw-shop-web"

    replay = parse_sse(state.log.sse_replay(case["id"])[0])
    names = [name for name, _seq, _payload in replay]
    assert names.count(EventName.step_started) == 7
    assert names.count(EventName.step_finished) == 7
    assert names.count(EventName.finding_added) == 6
    assert names.count(EventName.dns_captured) == 1
    assert names.count(EventName.action_proposed) == 4
    assert EventName.action_applied not in names
    assert EventName.teardown_done not in names

    quarantine = next(action for action in detail["actions"]
                      if action["kind"] == ActionKind.quarantine_firewall.value)
    approved = await client.post(
        f"/cases/{case['id']}/actions/{quarantine['id']}/approve",
        headers=human, json={"approved_by": "operator"},
    )
    assert approved.status_code == 200, approved.text
    closed = await client.post(f"/cases/{case['id']}/close", headers=human)
    assert closed.status_code == 200, closed.text

    final_names = [name for name, _seq, _payload in parse_sse((await client.get(
        f"/cases/{case['id']}/stream", headers=human
    )).text)]
    assert EventName.action_applied in final_names
    assert EventName.teardown_done in final_names


@pytest.mark.asyncio
async def test_each_fake_case_resets_production(client, human, state):
    state.vultr.instances["inst-shop-prod"].firewall_group_id = "fw-old-quarantine"
    state.vultr.instances["inst-shop-prod"].power_status = "stopped"

    response = await client.post("/dev/fake-case", headers=human, json={})

    assert response.status_code == 201, response.text
    production = state.vultr.instances["inst-shop-prod"]
    assert production.firewall_group_id == "fw-shop-web"
    assert production.power_status == "running"
