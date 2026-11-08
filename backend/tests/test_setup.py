"""Setup: the app boots, FakeVultr is the default client, GET /instances lists
the account's servers (F1's read half)."""
from __future__ import annotations

from contracts.vultr import FakeVultr


async def test_healthz(client):
    r = await client.get("/healthz")
    assert r.status_code == 200 and r.json() == {"ok": True, "vultr": "fake"}


async def test_get_instances_lists_account_servers(client):
    r = await client.get("/instances")
    assert r.status_code == 200
    instances = r.json()
    assert {i["id"] for i in instances} == {FakeVultr.SHOP_PROD, FakeVultr.CLEAN_CONTROL}
    shop = next(i for i in instances if i["id"] == FakeVultr.SHOP_PROD)
    assert shop["label"] == "shop-prod" and shop["main_ip"] == "45.77.10.20"
    assert shop["firewall_group_id"] == "fw-shop-web"


async def test_openapi_exists_for_the_frontend(client):
    r = await client.get("/openapi.json")
    assert r.status_code == 200
    assert "/instances" in r.json()["paths"]
