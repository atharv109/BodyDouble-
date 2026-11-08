from __future__ import annotations

import asyncio
import ipaddress

import pytest

from contracts.vultr import FakeVultr
from contracts.models import VultrVPC

from backend.config import test_settings as make_test_settings
from backend.state import build_state


def _real_settings(tmp_path):
    settings = make_test_settings(f"sqlite:///{(tmp_path / 'shared.db').as_posix()}")
    settings.vultr_api_key = "fake-vultr-key"
    settings.operator_password = "correct-horse-battery"
    settings.app_secret = "s" * 64
    settings.investigation_vpc_id = "vpc-investigation"
    settings.investigation_vpc_subnet = "10.77.0.0/29"
    settings.control_url = "http://10.77.0.1:8000"
    return settings


async def test_concurrent_cases_share_vpc_with_distinct_ips_and_teardown_keeps_it(
        tmp_path):
    settings = _real_settings(tmp_path)
    fake = FakeVultr()
    fake.vpcs[settings.investigation_vpc_id] = VultrVPC(
        id=settings.investigation_vpc_id, region="ewr", description="shared",
        v4_subnet="10.77.0.0", v4_subnet_mask=29)
    state = build_state(settings, vultr=fake)
    try:
        first = await state.service.open_case("inst-shop-prod", "first")
        second = await state.service.open_case("inst-clean-control", "second")
        await asyncio.gather(
            state.service.run_case(first.id, force_full=True, auto_close=False),
            state.service.run_case(second.id, force_full=True, auto_close=False),
        )
        rows = [state.service.row(first.id), state.service.row(second.id)]
        addresses = [row.twin_internal_ip for row in rows]
        network = ipaddress.ip_network(settings.investigation_vpc_subnet)
        control = ipaddress.ip_address("10.77.0.1")
        assert len(set(addresses)) == 2
        for address in map(ipaddress.ip_address, addresses):
            assert address in network
            assert address not in {network.network_address,
                                   network.broadcast_address, control}
        assert all(row.vpc_id == settings.investigation_vpc_id for row in rows)
        session_ips = {session.vpc_ip for session in state.channel.sessions.values()
                       if session.case_id in {first.id, second.id}}
        assert session_ips == set(addresses)
        assert not any(method == "POST" and path == "/v2/vpcs"
                       for method, path, _body in fake.calls)

        await state.service.close_case(first.id)
        await state.service.close_case(second.id)
        assert settings.investigation_vpc_id in fake.vpcs
        assert not any(method == "DELETE" and
                       path == f"/v2/vpcs/{settings.investigation_vpc_id}"
                       for method, path, _body in fake.calls)

        # Terminal cases release their reservations for later twins.
        third = await state.service.open_case("inst-shop-prod", "third")
        await state.service.run_case(third.id, force_full=True, auto_close=False)
        assert state.service.row(third.id).twin_internal_ip in addresses
    finally:
        for task in state.fake_twin_tasks.values():
            task.cancel()
        await asyncio.gather(*state.fake_twin_tasks.values(), return_exceptions=True)
        state.close()


@pytest.mark.parametrize("missing", ["id", "subnet", "control_url"])
def test_real_mode_refuses_incomplete_shared_vpc_configuration(tmp_path, missing):
    settings = _real_settings(tmp_path)
    if missing == "id":
        settings.investigation_vpc_id = None
    elif missing == "subnet":
        settings.investigation_vpc_subnet = None
    else:
        settings.control_url = None
    with pytest.raises(RuntimeError, match="BD_VPC_ID, BD_VPC_SUBNET, and CONTROL_URL"):
        build_state(settings, vultr=FakeVultr())
