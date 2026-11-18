"""B2: /healthz reports vultr:"real" while a real-mode run is live, and
"vultr":"fake" otherwise. The real-mode state here only *constructs* a
RealVultr client (validated settings, offline) — no live Vultr calls.
"""
from __future__ import annotations

import httpx

from backend.config import test_settings as make_test_settings
from backend.state import build_state
from contracts.vultr import RealVultr

REAL_MODE_OVERRIDES = {
    "bd_real_mode": True,
    "vultr_api_key": "test-key",
    "operator_password": "operator-password-12",
    "app_secret": "z" * 40,
    "investigation_vpc_id": "vpc-test",
    "investigation_vpc_subnet": "10.1.96.0/24",
    "control_url": "http://10.1.96.4:8000",
}


async def test_fake_mode_healthz(state, client):
    r = await client.get("/healthz")
    assert r.status_code == 200
    assert r.json() == {"ok": True, "vultr": "fake"}


async def test_real_mode_healthz(tmp_path):
    settings = make_test_settings(f"sqlite:///{(tmp_path / 'healthz.db').as_posix()}")
    for k, v in REAL_MODE_OVERRIDES.items():
        setattr(settings, k, v)
    st = build_state(settings)  # make_vultr_client picks RealVultr (offline)
    assert isinstance(st.vultr, RealVultr)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=st.app),
                                     base_url="http://t") as client:
            r = await client.get("/healthz")
            assert r.status_code == 200
            assert r.json() == {"ok": True, "vultr": "real"}
    finally:
        await st.vultr.aclose()
        st.close()
