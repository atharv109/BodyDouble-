from __future__ import annotations

import pytest

from contracts.events import TeardownDone
from contracts.models import CaseState
from contracts.vultr import VultrNotFound

from conftest import open_env


@pytest.mark.asyncio
async def test_close_deletes_twin_and_vpc_and_records_404(tmp_path):
    async with open_env(tmp_path) as (state, client):
        opened = await state.service.open_case("inst-shop-prod", "suspected breach")
        sealed = await state.service.run_case(opened.id)
        assert sealed.state is CaseState.sealed
        row = state.service.row(opened.id)
        twin_id, vpc_id, firewall_id = (
            row.twin_instance_id, row.vpc_id, row.firewall_group_id
        )
        state.service._move(row, CaseState.investigating, "test investigation")
        state.service._move(row, CaseState.reported, "test report")

        response = await client.post(f"/cases/{opened.id}/close")

        assert response.status_code == 200, response.text
        assert response.json()["case"]["state"] == "closed"
        with pytest.raises(VultrNotFound):
            await state.vultr.get_instance(twin_id)
        assert vpc_id not in state.vultr.vpcs
        assert firewall_id not in state.vultr.firewall_groups
        entries = state.log.entries(opened.id)
        event = next(e for e in entries if e.event == "teardown_done")
        teardown = TeardownDone.model_validate(event.payload)
        assert teardown.twin_instance_id == twin_id
        assert teardown.twin_status_code == 404
        assert teardown.vpc_deleted is True


@pytest.mark.asyncio
async def test_failed_case_still_tears_down_in_finally(tmp_path):
    async with open_env(
        tmp_path, spawn_fake_twin=False, register_timeout_s=0.01
    ) as (state, _client):
        opened = await state.service.open_case("inst-shop-prod", "registration failure")
        failed = await state.service.run_case(opened.id)

        assert failed.state is CaseState.failed
        with pytest.raises(VultrNotFound):
            await state.vultr.get_instance(failed.twin_instance_id)
        teardown = next(
            e for e in state.log.entries(opened.id) if e.event == "teardown_done"
        )
        assert teardown.payload["twin_status_code"] == 404
