"""F1: GET /instances lists the account's instances; POST /cases opens a case
on one. Done when: case row created with instance ID, reason, timestamp."""
from __future__ import annotations

from sqlalchemy import select

from contracts.models import GENESIS_HASH, Actor, CaseState
from contracts.vultr import FakeVultr

from backend.db import CaseRow, LogEntryRow


async def test_open_case_creates_row_with_instance_reason_and_ts(client, state):
    r = await client.post("/cases", json={
        "instance_id": FakeVultr.SHOP_PROD, "reason": "irregular auth log entries"})
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["id"] == "case-0001"
    assert body["instance_id"] == FakeVultr.SHOP_PROD
    assert body["instance_label"] == "shop-prod"
    assert body["reason"] == "irregular auth log entries"
    # POST /cases keeps walking the case; `opened` is proven by the log (test below)
    assert body["state"] != CaseState.failed.value
    assert body["created_at"]

    with state.sf() as s:
        row = s.get(CaseRow, "case-0001")
        assert row is not None
        assert row.instance_id == FakeVultr.SHOP_PROD
        assert row.reason == "irregular auth log entries"
        assert row.created_at is not None


async def test_open_case_logs_state_change_by_human(client, state):
    await client.post("/cases", json={
        "instance_id": FakeVultr.SHOP_PROD, "reason": "cpu pegged"})
    with state.sf() as s:
        rows = list(s.execute(select(LogEntryRow).order_by(LogEntryRow.seq)).scalars())
    assert rows, "no log entries"
    e = rows[0]
    assert e.seq == 0 and e.case_id == "case-0001"
    assert e.actor == Actor.human.value
    assert e.event == "state_changed"
    assert e.prev_hash == GENESIS_HASH
    assert e.payload["to_state"] == CaseState.opened.value
    assert e.payload["from_state"] is None
    assert e.hash


async def test_open_case_rejects_unknown_instance(client):
    r = await client.post("/cases", json={"instance_id": "inst-nope", "reason": "x"})
    assert r.status_code == 404


async def test_open_case_requires_reason(client):
    r = await client.post("/cases", json={"instance_id": FakeVultr.SHOP_PROD, "reason": ""})
    assert r.status_code == 422
