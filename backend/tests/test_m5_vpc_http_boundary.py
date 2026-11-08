from __future__ import annotations

import asyncio

from contracts.models import VultrVPC
from contracts.vultr import FakeVultr

from backend.config import test_settings as make_test_settings
from backend.state import build_state
from conftest import make_src_client


async def test_vpc_http_boundary_and_session_ip_binding(tmp_path, caplog):
    settings = make_test_settings(f"sqlite:///{(tmp_path / 'm5.db').as_posix()}")
    settings.vultr_api_key = "fake-vultr-key"
    settings.operator_password = "correct-horse-battery"
    settings.app_secret = "m" * 64
    settings.investigation_vpc_id = "vpc-investigation"
    settings.investigation_vpc_subnet = "10.77.0.0/29"
    settings.control_url = "http://10.77.0.1:8000"
    fake = FakeVultr()
    fake.vpcs[settings.investigation_vpc_id] = VultrVPC(
        id=settings.investigation_vpc_id, region="ewr", description="shared",
        v4_subnet="10.77.0.0", v4_subnet_mask=29)
    state = build_state(settings, vultr=fake)
    try:
        case = await state.service.open_case("inst-shop-prod", "M5 boundary")
        await state.service.run_case(case.id, force_full=True, auto_close=False)
        row = state.service.row(case.id)
        session = next(item for item in state.channel.sessions.values()
                       if item.case_id == case.id)
        assert session.vpc_ip == row.twin_internal_ip

        async with make_src_client(state.app, row.twin_internal_ip) as twin_client:
            assert (await twin_client.get(f"/cases/{case.id}")).status_code == 404
            assert (await twin_client.get("/instances")).status_code == 404
            heartbeat = await twin_client.post(
                "/twin/heartbeat", headers={"X-Twin-Session": session.key})
            assert heartbeat.status_code == 204, heartbeat.text
        assert "blocked non-twin request from investigation VPC" in caplog.text

        other_ip = "10.77.0.6"
        assert other_ip != row.twin_internal_ip
        async with make_src_client(state.app, other_ip) as other_client:
            stolen = await other_client.post(
                "/twin/heartbeat", headers={"X-Twin-Session": session.key})
            assert stolen.status_code == 403
            assert "different VPC IP" in stolen.text
    finally:
        for task in state.fake_twin_tasks.values():
            task.cancel()
        await asyncio.gather(*state.fake_twin_tasks.values(), return_exceptions=True)
        state.close()
