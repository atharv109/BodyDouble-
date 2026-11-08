"""Setup: the app boots, FakeVultr is the default client, GET /instances lists
the account's servers behind the human session (F1's read half), and the
session scheme is the only way in for humans."""
from __future__ import annotations

from contracts.vultr import FakeVultr


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True, "vultr": "fake"}


async def test_get_instances_lists_account_servers(client, human):
    client.cookies.clear()
    r = await client.get("/instances")
    assert r.status_code == 401  # human session required
    r = await client.get("/instances", headers=human)
    assert r.status_code == 200
    instances = r.json()
    assert {i["id"] for i in instances} == {FakeVultr.SHOP_PROD, FakeVultr.CLEAN_CONTROL}
    shop = next(i for i in instances if i["id"] == FakeVultr.SHOP_PROD)
    assert shop["label"] == "shop-prod" and shop["main_ip"] == "45.77.10.20"
    assert shop["firewall_group_id"] == "fw-shop-web"


async def test_session_endpoint_mints_and_cookie_works(client):
    r = await client.post("/auth/session", json={"operator": "alice"})
    assert r.status_code == 200
    token = r.json()["session_token"]
    assert r.headers["set-cookie"].startswith("bd_session=")
    # the cookie alone authorizes (EventSource in the browser sends no headers)
    client.cookies.set("bd_session", token)
    r2 = await client.get("/instances")
    assert r2.status_code == 200
    client.cookies.clear()
    # a tampered token is rejected (cookie cleared so only the header counts)
    client.cookies.clear()
    r3 = await client.get("/instances", headers={"X-Human-Session": token[:-2] + "zz"})
    assert r3.status_code == 401


async def test_openapi_exists_for_the_frontend(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    assert "/instances" in r.json()["paths"]
