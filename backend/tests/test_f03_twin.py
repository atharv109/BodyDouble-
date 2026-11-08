"""F3: create the twin from the snapshot on a dedicated VPC with an inbound-deny
firewall group, booting the forensics ISO. Done when: twin instance ID stored;
ISO attached before the cloned OS boots (snapshot_id + iso_id in one create
call; the T1 fallback behind settings.t1_fallback)."""
from __future__ import annotations

import base64
import json

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
    user_data = json.loads(base64.b64decode(create[2]["user_data"]))
    assert set(user_data) == {
        "case_id", "token", "control_plane", "vpc_subnet", "vpc_ip",
    }
    assert user_data["case_id"] == case["id"]
    assert user_data["token"].startswith("twreg-")
    assert user_data["control_plane"] == "http://10.0.0.1:8000"
    assert user_data["vpc_subnet"] == f"{fake.vpcs[vpc_id].v4_subnet}/24"
    assert user_data["vpc_ip"] == fake.instances[twin_id].internal_ip
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


async def test_t1_fallback_restores_snapshot_while_iso_stays_attached(tmp_path):
    fake = FakeVultr()
    async with open_env(tmp_path, fake=fake, t1_fallback=True) as (st, client):
        r = await client.post("/cases", json={
            "instance_id": FakeVultr.SHOP_PROD, "reason": "cpu pegged"})
        case = r.json()
        assert case["twin_instance_id"]
        twin_id = case["twin_instance_id"]

        # created from the ISO alone, then restored while the ISO stays attached
        create = next(c for c in fake.calls if c[:2] == ("POST", "/v2/instances"))
        assert create[2]["iso_id"] == ISO_ID
        assert "snapshot_id" not in create[2]
        restore = ("POST", f"/v2/instances/{twin_id}/restore",
                   {"snapshot_id": case["snapshot_id"]})
        restore_i = fake.calls.index(restore)
        poll_i = next(i for i, c in enumerate(fake.calls)
                      if c[:2] == ("GET", f"/v2/instances/{twin_id}"))
        assert restore_i < poll_i
        assert fake.isos[twin_id] == ISO_ID
        assert fake.instances[twin_id].status == "active"


class _RestoreExplodes(FakeVultr):
    """T1 fallback path where snapshot restore dies unexpectedly."""

    async def restore_snapshot(self, instance_id: str, snapshot_id: str) -> None:
        raise RuntimeError("snapshot restore exploded")


async def test_unexpected_failure_fails_case_and_keeps_twin_id(tmp_path):
    fake = _RestoreExplodes()
    async with open_env(tmp_path, fake=fake, t1_fallback=True) as (st, client):
        r = await client.post("/cases", json={
            "instance_id": FakeVultr.SHOP_PROD, "reason": "x"})
        # the case row is the outcome even when something unexpected blows up
        assert r.status_code == 201, r.text
        case = r.json()
        assert case["state"] == CaseState.failed.value
        # the live twin's id was persisted before the failure, so F11 teardown
        # found and destroyed it — never orphan the instance
        assert case["twin_instance_id"] not in fake.instances
        teardown = next(
            e for e in st.log.entries(case["id"]) if e.event == "teardown_done"
        )
        assert teardown.payload["twin_status_code"] == 404
        with st.sf() as s:
            row = s.get(CaseRow, case["id"])
        assert row.twin_instance_id == case["twin_instance_id"]


async def test_vultr_rejecting_combined_create_autofalls_back(tmp_path):
    fake = FakeVultr(reject_snapshot_plus_iso=True)  # day-one test T1 failure
    async with open_env(tmp_path, fake=fake) as (st, client):
        r = await client.post("/cases", json={
            "instance_id": FakeVultr.SHOP_PROD, "reason": "x"})
        case = r.json()
        assert case["state"] == CaseState.sealed.value
        creates = [c for c in fake.calls if c[:2] == ("POST", "/v2/instances")]
        assert len(creates) == 2                     # combined attempt, then retry
        assert creates[0][2]["iso_id"] == ISO_ID      # rejected by Vultr (T1)
        assert creates[1][2]["iso_id"] == ISO_ID      # retry boots trusted ISO
        assert "snapshot_id" not in creates[1][2]
        twin_id = case["twin_instance_id"]
        assert fake.isos[twin_id] == ISO_ID
        assert ("POST", f"/v2/instances/{twin_id}/restore",
                {"snapshot_id": case["snapshot_id"]}) in fake.calls
