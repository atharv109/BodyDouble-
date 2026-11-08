"""F2: snapshot the suspect instance through VultrClient and poll until
complete. Done when: snapshot ID stored; status `complete`."""
from __future__ import annotations

from contracts.models import CaseState
from contracts.vultr import FakeVultr

from backend.db import EvidenceRow


async def test_snapshot_stored_and_polled_to_complete(client, state, fake):
    r = await client.post("/cases", json={
        "instance_id": FakeVultr.SHOP_PROD, "reason": "cpu pegged"})
    case = r.json()
    assert case["snapshot_id"] is not None
    # polled until the Vultr API reports complete
    assert fake.snapshots[case["snapshot_id"]].status == "complete"
    # the snapshot was taken of the production instance through the client
    assert ("POST", "/v2/snapshots",
            {"instance_id": FakeVultr.SHOP_PROD,
             "description": f"body-double case {case['id']}"}) in fake.calls
    # state: opened -> snapshotting, and the poll loop ran at least twice
    assert case["state"] == CaseState.snapshotting.value
    polls = [c for c in fake.calls if c[0] == "GET"
             and c[1] == f"/v2/snapshots/{case['snapshot_id']}"]
    assert len(polls) >= 2


async def test_snapshot_is_evidence_item_one(client, state):
    r = await client.post("/cases", json={
        "instance_id": FakeVultr.SHOP_PROD, "reason": "cpu pegged"})
    case = r.json()
    with state.sf() as s:
        ev = list(s.query(EvidenceRow).all())
    assert len(ev) == 1
    assert ev[0].path == f"snapshot:{case['snapshot_id']}"
    assert ev[0].sha256 and len(ev[0].sha256) == 64
    assert f"snapshot {case['snapshot_id']} of" in ev[0].excerpt
