from __future__ import annotations

import asyncio
import re

import httpx

from contracts.models import Attack
from contracts.vultr import FakeVultr

from backend.config import test_settings as make_test_settings
from backend.state import build_state


async def _infect(client, human, attacks):
    response = await client.post("/dev/infect", headers=human,
                                 json={"attacks": attacks})
    assert response.status_code == 201, response.text
    return response.json()


async def test_infect_one_attack_filters_fixture(client, state, human):
    result = await _infect(client, human, [Attack.cron_backdoor.value])
    assert result["alert_id"] is not None
    detail = (await client.get(f"/cases/{result['case_id']}", headers=human)).json()
    assert detail["case"]["state"] == "reported"
    assert [finding["id"] for finding in detail["findings"]] == ["fd-01"]
    assert [step["seq"] for step in detail["steps"]] == [2]
    assert {item["path"] for item in detail["evidence"]} == {
        detail["evidence"][0]["path"], "/etc/cron.d/sysupdate"
    }
    assert detail["evidence"][0]["path"].startswith("snapshot:")
    assert [action["id"] for action in detail["actions"]] == [
        "act-1", "act-3", "act-4"
    ]
    assert "dns_captured" not in [entry.event for entry in state.log.entries(
        result["case_id"])]


async def test_infect_all_five_replays_all_mapped_content(client, state, human):
    attacks = [attack.value for attack in Attack]
    result = await _infect(client, human, attacks)
    detail = (await client.get(f"/cases/{result['case_id']}", headers=human)).json()
    assert [finding["id"] for finding in detail["findings"]] == [
        f"fd-{index:02d}" for index in range(1, 7)
    ]
    assert [action["id"] for action in detail["actions"]] == [
        f"act-{index}" for index in range(1, 5)
    ]
    assert [step["seq"] for step in detail["steps"]] == [2, 3, 4, 5, 6, 7]
    assert [entry.event for entry in state.log.entries(result["case_id"])].count(
        "dns_captured") == 1


async def test_infect_none_is_clean_and_each_call_has_fresh_healthy_instance(
        client, human):
    first = await _infect(client, human, [])
    second = await _infect(client, human, [])
    assert first["instance_id"] != second["instance_id"]
    assert first["case_id"] != second["case_id"]
    assert first["alert_id"] is None and second["alert_id"] is None
    for result in (first, second):
        detail = (await client.get(f"/cases/{result['case_id']}", headers=human)).json()
        assert detail["case"]["state"] == "reported"
        assert detail["findings"] == []
        assert detail["actions"] == []

    instances = (await client.get("/instances", headers=human)).json()
    by_id = {item["id"]: item for item in instances}
    for result in (first, second):
        assert re.fullmatch(r"demo-[0-9a-f]{4}", by_id[result["instance_id"]]["label"])
    sensors = (await client.get("/sensors", headers=human)).json()
    sensor_by_id = {item["instance_id"]: item for item in sensors}
    assert all(sensor_by_id[result["instance_id"]]["healthy"]
               for result in (first, second))


async def test_infect_is_404_in_real_mode(tmp_path):
    settings = make_test_settings(f"sqlite:///{(tmp_path / 'real.db').as_posix()}")
    settings.vultr_api_key = "not-a-real-key"
    settings.operator_password = "correct-horse-battery"
    settings.app_secret = "a" * 32
    settings.investigation_vpc_id = "vpc-shared"
    settings.investigation_vpc_subnet = "10.77.0.0/24"
    settings.control_url = "http://10.77.0.1:8000"
    state = build_state(settings, vultr=FakeVultr())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=state.app), base_url="http://t"
        ) as client:
            session = await client.post("/auth/session", json={
                "operator": "operator", "password": settings.operator_password,
            })
            headers = {"X-Human-Session": session.json()["session_token"]}
            response = await client.post("/dev/infect", headers=headers,
                                         json={"attacks": []})
            assert response.status_code == 404
    finally:
        for task in state.fake_twin_tasks.values():
            task.cancel()
        await asyncio.gather(*state.fake_twin_tasks.values(), return_exceptions=True)
        state.close()
