"""F3: create the twin from the snapshot on a dedicated VPC with an inbound-deny
firewall group, booting the forensics ISO. Done when: twin instance ID stored;
ISO attached before the cloned OS boots (snapshot_id + iso_id in one create
call; the T1 fallback behind settings.t1_fallback)."""
from __future__ import annotations

from contracts.models import CaseState
from contracts.vultr import FakeVultr

from backend.db import CaseRow
from conftest import open_env

ISO_ID = "iso-bd-forensics"


async def test_twin_created_on_dedicated_vpc_with_inbound_deny(client, state, fake, human):
    r = await client.post("/cases", headers=human, json={
        "instance_id": FakeVultr.SHOP_PROD, "reason": "cpu pegged"})
    case = r.json()
    twin_id, vpc_id, fw_id = case["twin_instance_id"], case["vpc_id"], case["firewall_group_id"]
    assert twin_id and vpc_id and fw_id
    # twin built and sealed (F4: the in-process twin registers on boot)
    assert case["state"] == CaseState.sealed.value

    # dedicated VPC, in the same region as the source instance
    assert fake.vpcs[vpc_id].region == "ewr"
    assert case["id"] in fake.vpcs[vpc_id].description
    # inbound-deny firewall group: attached to the twin, allows no rules at all
    assert fake.firewall_rules[fw_id] == []
    assert fake.instances[twin_id].firewall_group_id == fw_id
    assert fake.instances[twin_id].vpc_ids == [vpc_id]

    # one create call: restored from the case's snapshot, booting the forensics ISO
    create = next(c for c in fake.calls if c[:2] == ("POST", "/v2/instances"))
    assert create[2]["snapshot_id"] == case["snapshot_id"]
    assert create[2]["iso_id"] == ISO_ID
    assert create[2]["attach_vpc"] == [vpc_id]
    assert create[2]["firewall_group_id"] == fw_id
    assert fake.instances[twin_id].os == "Snapshot"
    # ISO attached, and the twin booted (Vultr reports it active)
    assert fake.isos[twin_id] == ISO_ID
    assert fake.instances[twin_id].status == "active"

    # VPC details stored on the case: the twin channel (F4) only accepts calls
    # from this subnet
    with state.sf() as s:
        row = s.get(CaseRow, case["id"])
        assert row.vpc_subnet == fake.vpcs[vpc_id].v4_subnet
        assert row.vpc_mask == fake.vpcs[vpc_id].v4_subnet_mask


async def test_t1_fallback_attaches_iso_before_the_cloned_os_boots(tmp_path):
    fake = FakeVultr()
    async with open_env(tmp_path, fake=fake, t1_fallback=True) as (st, client):
        r = await client.post("/cases", json={
            "instance_id": FakeVultr.SHOP_PROD, "reason": "cpu pegged"})
        case = r.json()
        assert case["twin_instance_id"]
        twin_id = case["twin_instance_id"]

        # created from the snapshot alone, no iso_id in the create call
        create = next(c for c in fake.calls if c[:2] == ("POST", "/v2/instances"))
        assert "iso_id" not in create[2]
        # ... and the ISO attach lands before the first boot poll, so the
        # forensics ISO is in the drive before the cloned OS could boot
        attach = ("POST", f"/v2/instances/{twin_id}/iso/attach", {"iso_id": ISO_ID})
        attach_i = fake.calls.index(attach)
        poll_i = next(i for i, c in enumerate(fake.calls)
                      if c[:2] == ("GET", f"/v2/instances/{twin_id}"))
        assert attach_i < poll_i
        assert fake.isos[twin_id] == ISO_ID
        assert fake.instances[twin_id].status == "active"
