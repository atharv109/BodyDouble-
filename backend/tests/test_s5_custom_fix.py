from __future__ import annotations

from contracts.models import ActionKind, ActionStatus


async def _reported_demo(client, human):
    response = await client.post("/dev/fake-case", headers=human, json={})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def test_exactly_one_agent_action_is_recommended(client, human):
    case_id = await _reported_demo(client, human)
    detail = (await client.get(f"/cases/{case_id}", headers=human)).json()
    agent_actions = [action for action in detail["actions"]
                     if action["created_by"] == "agent"]
    recommended = [action for action in agent_actions if action["recommended"]]
    assert len(recommended) == 1
    assert recommended[0]["kind"] == ActionKind.quarantine_firewall.value


async def test_custom_api_fields_are_ignored_and_reported_state_is_required(
        client, human):
    opened = await client.post("/cases", headers=human, json={
        "instance_id": "inst-clean-control", "reason": "not yet reported",
    })
    assert opened.status_code == 201
    conflict = await client.post(f"/cases/{opened.json()['id']}/actions", headers=human,
                                 json={
                                     "kind": "stop_instance",
                                     "description": "stop it",
                                     "created_by": "operator",
                                 })
    assert conflict.status_code == 409

    case_id = await _reported_demo(client, human)
    response = await client.post(f"/cases/{case_id}/actions", headers=human, json={
        "kind": "stop_instance",
        "description": "Operator wants this host stopped",
        "created_by": "alice",
        "api_path": "/v2/account",
        "api_body": {"steal": "everything"},
    })
    assert response.status_code == 201, response.text
    action = response.json()
    assert action["created_by"] == "human"
    assert action["recommended"] is False
    assert action["api_method"] == "POST"
    assert action["api_path"] == "/v2/instances/inst-shop-prod/halt"
    assert action["api_body"] is None
    assert "/v2/account" not in action["api_path"]


async def test_approved_manual_plan_is_logged_applied_without_vultr_call(
        client, state, human):
    case_id = await _reported_demo(client, human)
    created = await client.post(f"/cases/{case_id}/actions", headers=human, json={
        "kind": "manual_plan",
        "description": "Drain traffic, patch package, then verify hashes",
        "created_by": "alice",
        "api_path": "/v2/account",
        "api_body": {"forbidden": True},
    })
    assert created.status_code == 201, created.text
    action = created.json()
    assert action["api_method"] is None
    assert action["api_path"] is None
    assert action["api_body"] is None
    fake = state.vultr
    calls_before = list(fake.calls)

    approved = await client.post(
        f"/cases/{case_id}/actions/{action['id']}/approve",
        headers=human, json={"approved_by": "mallory"},
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == ActionStatus.applied.value
    assert approved.json()["approved_by"] == "operator"
    assert fake.calls == calls_before
    events = [entry.event for entry in state.log.entries(case_id)]
    assert events[-2:] == ["action_approved", "action_applied"]
