"""Contract tests. Every worker runs these after rebasing: `uv run pytest contracts`."""
import json
from pathlib import Path

import pytest

from contracts import hashing
from contracts.endpoints import ENDPOINTS
from contracts.events import EventName, parse_sse
from contracts.fixtures import make_fixture
from contracts.models import (
    GENESIS_HASH, Actor, CaseDetail, CaseState, CreateTwinRequest, LogEntry, can_transition,
)
from contracts.vultr import FakeVultr, VultrError, VultrNotFound

FIX = Path(make_fixture.__file__).parent


# ------------------------------------------------------------- fixture
def test_fixture_is_current():
    sse, detail = make_fixture.build()
    assert (FIX / "fake_case.sse").read_text(encoding="utf-8") == sse, "re-run make_fixture"
    assert json.loads((FIX / "fake_case_detail.json").read_text(encoding="utf-8")) == json.loads(
        detail.model_dump_json())
    for name, schema in make_fixture.schemas().items():
        assert json.loads((FIX.parent / "schema" / f"{name}.json").read_text(encoding="utf-8")) == schema


def test_fixture_parses_and_covers_every_event():
    events = parse_sse((FIX / "fake_case.sse").read_text(encoding="utf-8"))
    assert {n for n, _, _ in events} == set(EventName)
    assert [s for _, s, _ in events] == list(range(len(events)))


def test_fixture_state_walk_is_legal_and_complete():
    events = parse_sse((FIX / "fake_case.sse").read_text(encoding="utf-8"))
    walk = [p.to_state for n, _, p in events if n is EventName.state_changed]
    assert walk == [CaseState.opened, CaseState.snapshotting, CaseState.restoring, CaseState.sealed,
                    CaseState.investigating, CaseState.reported, CaseState.contained, CaseState.closed]
    for a, b in zip(walk, walk[1:]):
        assert can_transition(a, b)


def test_fixture_findings_cite_existing_evidence_and_five_indicators():
    d = CaseDetail.model_validate_json((FIX / "fake_case_detail.json").read_text(encoding="utf-8"))
    ev_ids = {e.id for e in d.evidence}
    assert all(set(f.evidence_ids) <= ev_ids for f in d.findings)
    paths = {e.path for e in d.evidence}
    for planted in ["/etc/cron.d/sysupdate", "/root/.ssh/authorized_keys", "/usr/bin/top",
                    "dns:beacon.c2.example", "/root/NOTE_FOR_AI_ANALYST.txt"]:
        assert planted in paths
    assert any(e.injection_flag for e in d.evidence)
    assert d.blast_radius.model_dump() == {"prod_writes_before_approval": 0, "packets_out": 0, "containers_left": 0}


# ------------------------------------------------------------- state machine
def test_failed_reachable_from_any_live_state():
    for s in CaseState:
        assert can_transition(s, CaseState.failed) == (s not in (CaseState.closed, CaseState.failed))
    assert not can_transition(CaseState.opened, CaseState.investigating)


# ------------------------------------------------------------- hash chain
def _chain(n):
    from datetime import datetime, timezone
    out, prev = [], GENESIS_HASH
    for i in range(n):
        e = LogEntry(seq=i, case_id="c", ts=datetime(2026, 11, 7, tzinfo=timezone.utc), actor=Actor.system,
                     event="x", payload={"i": i}, prev_hash=prev, hash="")
        e.hash = hashing.entry_hash(e)
        prev = e.hash
        out.append(e)
    return out


def test_hash_chain_detects_tampering():
    chain = _chain(4)
    assert hashing.verify_chain(chain) is None
    chain[2].payload = {"i": 99}
    assert hashing.verify_chain(chain) == 2


# ------------------------------------------------------------- endpoints
def test_endpoints_cover_prd_table():
    have = {(e.method, e.path) for e in ENDPOINTS}
    for row in [("GET", "/instances"), ("POST", "/cases"), ("GET", "/cases/{id}"),
                ("GET", "/cases/{id}/stream"), ("POST", "/cases/{id}/actions/{action_id}/approve"),
                ("POST", "/cases/{id}/close"), ("GET", "/cases/{id}/bundle"), ("POST", "/twin/register")]:
        assert row in have


# ------------------------------------------------------------- FakeVultr
async def test_fake_vultr_full_lifecycle():
    v = FakeVultr()
    assert {i.label for i in await v.list_instances()} == {"shop-prod", "clean-control"}
    snap = await v.create_snapshot(FakeVultr.SHOP_PROD, "case-1")
    assert (await v.get_snapshot(snap.id)).status == "pending"
    assert (await v.get_snapshot(snap.id)).status == "complete"
    vpc = await v.create_vpc("ewr", "case-1")
    fw = await v.create_firewall_group("case-1 twin inbound-deny")
    twin = await v.create_instance(CreateTwinRequest(region="ewr", plan="vc2-1c-2gb", label="twin",
                                                     snapshot_id=snap.id, iso_id="iso-bd",
                                                     attach_vpc=[vpc.id], firewall_group_id=fw.id))
    assert v.isos[twin.id] == "iso-bd" and twin.internal_ip.startswith("10.")
    await v.delete_instance(twin.id)
    with pytest.raises(VultrNotFound):
        await v.get_instance(twin.id)
    await v.delete_vpc(vpc.id)


async def test_fake_vultr_t1_fallback_and_actions():
    v = FakeVultr(reject_snapshot_plus_iso=True)
    snap = await v.create_snapshot(FakeVultr.SHOP_PROD, "c")
    fw = await v.create_firewall_group("q")
    req = CreateTwinRequest(region="ewr", plan="p", label="t", snapshot_id=snap.id, iso_id="iso",
                            firewall_group_id=fw.id)
    with pytest.raises(VultrError):
        await v.create_instance(req)
    twin = await v.create_instance(req.model_copy(update={"iso_id": None}))
    await v.attach_iso(twin.id, "iso")
    r = await v.request("PATCH", f"/v2/instances/{FakeVultr.SHOP_PROD}", {"firewall_group_id": fw.id})
    assert r.status_code == 202 and v.instances[FakeVultr.SHOP_PROD].firewall_group_id == fw.id
    r = await v.request("POST", f"/v2/instances/{FakeVultr.SHOP_PROD}/halt")
    assert r.status_code == 204


@pytest.mark.parametrize("method,path,body", [
    ("GET", "https://evil.example/v2/instances/x", None),       # absolute URL -> key leak
    ("POST", "//evil.example/v2/instances/x/halt", None),        # scheme-relative
    ("DELETE", "/v2/instances/inst-shop-prod", None),            # not on the menu
    ("PATCH", "/v2/instances/../account", {"firewall_group_id": "f"}),
    ("PATCH", "/v2/instances/inst-shop-prod", {"os_id": 1}),     # body key not allowed
    ("PATCH", "/v2/instances/inst-shop-prod", None),
])
async def test_raw_request_allowlist(method, path, body):
    from contracts.vultr import DisallowedCall, RealVultr
    for client in (FakeVultr(), RealVultr(api_key="test-not-a-key")):
        with pytest.raises(DisallowedCall):
            await client.request(method, path, body)
