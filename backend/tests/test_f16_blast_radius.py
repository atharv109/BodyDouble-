from __future__ import annotations

import pytest

from contracts.models import CaseState


@pytest.mark.asyncio
async def test_fake_run_reports_zero_blast_radius(client, human):
    response = await client.post("/dev/fake-case", headers=human, json={})
    assert response.status_code == 201, response.text
    case_id = response.json()["id"]
    closed = await client.post(f"/cases/{case_id}/close", headers=human)
    assert closed.status_code == 200, closed.text
    detail = await client.get(f"/cases/{case_id}", headers=human)
    assert detail.json()["blast_radius"] == {
        "prod_writes_before_approval": 0,
        "packets_out": 0,
        "containers_left": 0,
    }


@pytest.mark.asyncio
async def test_injected_preapproval_production_write_is_nonzero(state):
    opened = await state.service.open_case("inst-shop-prod", "test blast radius")
    sealed = await state.service.run_case(opened.id)
    assert sealed.state is CaseState.sealed
    state.log.append(opened.id, "api_call", {
        "method": "PATCH",
        "path": "/v2/instances/inst-shop-prod",
        "body": {"firewall_group_id": "bad-preapproval-write"},
    })

    blast = state.service.blast_radius(opened.id)
    assert blast.prod_writes_before_approval == 1
    assert blast.packets_out == blast.containers_left == 0
