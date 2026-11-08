from __future__ import annotations

import httpx
import pytest

from backend.config import test_settings as make_test_settings
from backend.state import build_state
from contracts.vultr import FakeVultr

from conftest import make_src_client


@pytest.mark.asyncio
async def test_fake_mode_password_optional_and_config_reports_false(client):
    config = await client.get("/auth/config")
    assert config.status_code == 200
    assert config.json() == {"password_required": False}

    session = await client.post("/auth/session", json={"operator": "demo"})
    assert session.status_code == 200
    assert session.json()["password_required"] is False


def test_real_mode_refuses_missing_or_short_operator_password(tmp_path):
    for password in (None, "short"):
        settings = make_test_settings(
            f"sqlite:///{(tmp_path / ('db-' + str(password))).as_posix()}"
        )
        settings.vultr_api_key = "not-a-real-key"
        settings.operator_password = password
        settings.app_secret = "a" * 64
        with pytest.raises(RuntimeError, match="BD_OPERATOR_PASSWORD"):
            build_state(settings, vultr=FakeVultr())


@pytest.mark.asyncio
async def test_real_mode_requires_correct_password_and_disables_fake_case(tmp_path):
    settings = make_test_settings(f"sqlite:///{(tmp_path / 'real.db').as_posix()}")
    settings.vultr_api_key = "not-a-real-key"
    settings.operator_password = "correct-horse-battery"
    settings.app_secret = "b" * 64
    settings.investigation_vpc_id = "vpc-shared"
    settings.investigation_vpc_subnet = "10.77.0.0/24"
    settings.control_url = "http://10.77.0.1:8000"
    state = build_state(settings, vultr=FakeVultr())
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=state.app), base_url="http://t"
        ) as client:
            assert (await client.get("/auth/config")).json() == {
                "password_required": True
            }
            for body in (
                {"operator": "operator"},
                {"operator": "operator", "password": "wrong-password"},
            ):
                assert (await client.post("/auth/session", json=body)).status_code == 401
            good = await client.post("/auth/session", json={
                "operator": "operator", "password": "correct-horse-battery",
            })
            assert good.status_code == 200
            assert good.json()["password_required"] is True
            fake_case = await client.post(
                "/dev/fake-case",
                headers={"X-Human-Session": good.json()["session_token"]},
                json={},
            )
            assert fake_case.status_code == 404
    finally:
        state.close()


@pytest.mark.parametrize("secret", [
    "",
    "body-double-dev-secret",
    "CHANGE_ME_WITH_A_LONG_RANDOM_VALUE",
    "x" * 31,
])
def test_real_mode_refuses_weak_app_secret(tmp_path, secret):
    settings = make_test_settings(f"sqlite:///{(tmp_path / 'secret.db').as_posix()}")
    settings.vultr_api_key = "not-a-real-key"
    settings.operator_password = "correct-horse-battery"
    settings.app_secret = secret
    with pytest.raises(RuntimeError, match="strong APP_SECRET"):
        build_state(settings, vultr=FakeVultr())


@pytest.mark.asyncio
async def test_case_vpc_source_cannot_mint_or_use_human_session(
    state, client, human
):
    case = await client.post("/cases", headers=human, json={
        "instance_id": FakeVultr.SHOP_PROD, "reason": "establish case VPC",
    })
    assert case.status_code == 201, case.text

    async with make_src_client(state.app, "10.1.96.44") as vpc_client:
        mint = await vpc_client.post("/auth/session", json={"operator": "attacker"})
        assert mint.status_code == 403
        human_call = await vpc_client.get("/instances", headers=human)
        assert human_call.status_code == 403
