from __future__ import annotations

import pytest

from backend.warm_twin import warm_instance
from contracts.models import CaseState


@pytest.mark.asyncio
async def test_next_case_adopts_warm_twin_without_snapshot_or_create(state, client, human):
    warm = await warm_instance(state, "inst-shop-prod")
    snapshots_before = sum(1 for call in state.vultr.calls
                           if call[:2] == ("POST", "/v2/snapshots"))
    creates_before = sum(1 for call in state.vultr.calls
                         if call[:2] == ("POST", "/v2/instances"))

    response = await client.post("/cases", headers=human, json={
        "instance_id": "inst-shop-prod", "reason": "use the warm twin",
    })
    assert response.status_code == 201, response.text
    case = response.json()
    assert case["state"] == CaseState.sealed.value
    assert case["snapshot_id"] == warm.snapshot_id
    assert case["twin_instance_id"] == warm.twin_instance_id
    assert snapshots_before == sum(1 for call in state.vultr.calls
                                   if call[:2] == ("POST", "/v2/snapshots"))
    assert creates_before == sum(1 for call in state.vultr.calls
                                 if call[:2] == ("POST", "/v2/instances"))

    states = [entry.payload["to_state"] for entry in state.log.entries(case["id"])
              if entry.event == "state_changed"]
    assert states == ["opened", "snapshotting", "restoring", "sealed"]
