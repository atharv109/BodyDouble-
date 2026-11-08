from __future__ import annotations

import pytest

from contracts.events import EventName, parse_sse
from contracts.models import CaseState

from conftest import open_env


@pytest.mark.asyncio
async def test_fake_case_walks_full_pipeline_and_replays_valid_sse(tmp_path):
    async with open_env(tmp_path, full_pipeline=True) as (_state, client):
        opened = await client.post("/cases", json={
            "instance_id": "inst-shop-prod", "reason": "CPU at 100% overnight",
        })
        assert opened.status_code == 201, opened.text
        case = opened.json()
        assert case["state"] == CaseState.closed.value

        detail = await client.get(f"/cases/{case['id']}")
        assert detail.status_code == 200, detail.text
        body = detail.json()
        assert body["case"]["state"] == "closed"
        assert body["steps"] and body["findings"] and body["actions"]

        stream = await client.get(f"/cases/{case['id']}/stream")
        assert stream.status_code == 200
        events = parse_sse(stream.text)
        assert events
        assert all(isinstance(name, EventName) for name, _seq, _payload in events)
        states = [payload.to_state for name, _seq, payload in events
                  if name is EventName.state_changed]
        assert states == [
            CaseState.opened, CaseState.snapshotting, CaseState.restoring,
            CaseState.sealed, CaseState.investigating, CaseState.reported,
            CaseState.closed,
        ]

        resume = await client.get(
            f"/cases/{case['id']}/stream", headers={"Last-Event-ID": "3"}
        )
        resumed = parse_sse(resume.text)
        assert resumed and all(seq > 3 for _name, seq, _payload in resumed)
