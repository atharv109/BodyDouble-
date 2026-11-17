"""B3 groundwork: the t1_fallback post-restore path (run-13 T1b, driven by the
control plane). After the restore call the service: waits for the restore to
finish, re-patches user_data (the restore reverts it to the snapshot's
cloud-init — a stale registration token otherwise), then re-inserts the ISO
(the restore empties the CD drive while the API still reports isomounted;
runs 8-12 failed without the detach + attach).
"""
from __future__ import annotations

import base64
import json

import pytest

from contracts.models import CaseState, VultrVPC
from contracts.vultr import FakeVultr, VultrError

from backend.service import CaseService
from backend.db import CaseRow

from conftest import open_env

ISO_ID = "iso-bd-forensics"


async def test_fallback_repatches_user_data_and_reinserts_iso(tmp_path):
    fake = FakeVultr()
    async with open_env(tmp_path, fake=fake, t1_fallback=True) as (_st, client):
        r = await client.post("/cases", json={
            "instance_id": FakeVultr.SHOP_PROD, "reason": "x"})
        case = r.json()
        twin_id = case["twin_instance_id"]
        assert case["state"] == CaseState.sealed.value

        calls = fake.calls
        restore_i = calls.index(("POST", f"/v2/instances/{twin_id}/restore",
                                 {"snapshot_id": case["snapshot_id"]}))
        patch_i = next(i for i, c in enumerate(calls)
                       if c[:2] == ("PATCH", f"/v2/instances/{twin_id}"))
        detach_i = calls.index(("POST", f"/v2/instances/{twin_id}/iso/detach", None))
        attach_i = calls.index(("POST", f"/v2/instances/{twin_id}/iso/attach",
                                {"iso_id": ISO_ID}))
        assert restore_i < patch_i < detach_i < attach_i
        # the re-patched payload is the same registration envelope create carried
        create = next(c for c in calls if c[:2] == ("POST", "/v2/instances"))
        assert calls[patch_i][2] == {"user_data": create[2]["user_data"]}
        assert fake.isos[twin_id] == ISO_ID  # the post-swap boot needs the media


class _AttachNeverReady(FakeVultr):
    """The re-attach races the physical detach (needs the retry to land)."""

    def __init__(self):
        super().__init__()
        self.attach_attempts = 0

    async def attach_iso(self, instance_id: str, iso_id: str) -> None:
        self.attach_attempts += 1
        if self.attach_attempts <= 2:  # transient: drive not yet empty
            raise VultrError(400, {"error": "Failed to attach ISO: drive busy"})
        await super().attach_iso(instance_id, iso_id)


@pytest.fixture
def fast_retry(monkeypatch):
    """Shrink _retry_transient's backoff so the retry test stays fast."""
    original = CaseService._retry_transient

    async def quick(self, what, call, attempts: int = 6, delay_s: float = 20.0):
        return await original(self, what, call, attempts, delay_s=0.05)

    monkeypatch.setattr(CaseService, "_retry_transient", quick)


async def test_iso_reinsert_retries_transient_attach_errors(tmp_path, fast_retry):
    fake = _AttachNeverReady()
    async with open_env(tmp_path, fake=fake, t1_fallback=True) as (_st, client):
        r = await client.post("/cases", json={
            "instance_id": FakeVultr.SHOP_PROD, "reason": "x"})
        assert r.json()["state"] == CaseState.sealed.value
        assert fake.attach_attempts == 3  # two transient failures, then success


REAL_MODE_ENV = {"bd_real_mode": True, "vultr_api_key": "k",
                 "operator_password": "operator-password-12", "app_secret": "t" * 40,
                 "investigation_vpc_id": "vpc-shared", "investigation_vpc_subnet": "10.1.96.0/20",
                 "control_url": "http://10.1.96.4:8000"}


def fake_with_shared_vpc() -> FakeVultr:
    """FakeVultr that knows the shared investigation VPC, so the twin gets an
    API-assigned internal_ip as real Vultr does (W2-A: create returns it)."""
    fake = FakeVultr()
    fake.vpcs["vpc-shared"] = VultrVPC(id="vpc-shared", region="ewr", description="inv",
                                       v4_subnet="10.1.96.0", v4_subnet_mask=20)
    return fake


@pytest.fixture
def no_settle(monkeypatch):
    """Skip the 75 s real-mode restore settle (it is live-run-covered)."""
    async def instant(self, twin_id):
        return None
    monkeypatch.setattr(CaseService, "_wait_restore_settled", instant)


async def test_real_mode_reseals_fresh_token_and_assigned_vpc_ip(tmp_path, no_settle):
    """B3: after the restore, the sealed boot's envelope carries a FRESH token
    and the API-assigned VPC IP (create-time internal_ip); the case row stores
    both, and the fake twin registers + seals with the fresh token."""
    fake = fake_with_shared_vpc()
    async with open_env(tmp_path, fake=fake, t1_fallback=True, **REAL_MODE_ENV) as (st, client):
        r = await client.post("/auth/session", json={"operator": "operator",
                                                     "password": "operator-password-12"})
        client.headers["X-Human-Session"] = r.json()["session_token"]
        r = await client.post("/cases", json={
            "instance_id": FakeVultr.SHOP_PROD, "reason": "x"})
        case = r.json()
        assert case["state"] == CaseState.sealed.value, case
        twin_id = case["twin_instance_id"]

        calls = fake.calls
        patch = next(c for c in calls if c[:2] == ("PATCH", f"/v2/instances/{twin_id}"))
        create = next(c for c in calls if c[:2] == ("POST", "/v2/instances"))
        assert patch[2]["user_data"] != create[2]["user_data"]  # fresh envelope
        patched = json.loads(base64.b64decode(patch[2]["user_data"]))
        assert patched["vpc_ip"] == fake.instances[twin_id].internal_ip  # assigned
        assert patched["vpc_subnet"] == "10.1.96.0/20"
        with st.sf() as s:
            row = s.get(CaseRow, case["id"])
        assert row.reg_token is None          # consumed by the sealed registration
        assert row.twin_internal_ip == patched["vpc_ip"]
        # the token the sealed boot presented is the one the row held at register
        assert create[2]["user_data"] != patch[2]["user_data"]
        # ISO ends re-inserted (the sealed boot needs its media)
        assert fake.isos[twin_id] == "iso-bd-forensics"


async def test_real_mode_shared_vpc_ip_comes_from_settings_not_free_list(tmp_path, no_settle):
    """The B3 real-mode twin claims the API-assigned internal_ip, not a
    self-chosen free address (run-13 T4 finding: chosen IPs never ARP)."""
    fake = fake_with_shared_vpc()
    async with open_env(tmp_path, fake=fake, t1_fallback=True, **REAL_MODE_ENV) as (st, client):
        r = await client.post("/auth/session", json={"operator": "operator",
                                                     "password": "operator-password-12"})
        client.headers["X-Human-Session"] = r.json()["session_token"]
        r = await client.post("/cases", json={
            "instance_id": FakeVultr.SHOP_PROD, "reason": "x"})
        case = r.json()
        assert case["state"] == CaseState.sealed.value
        twin_id = case["twin_instance_id"]
        envelope = json.loads(base64.b64decode(next(
            c for c in fake.calls
            if c[:2] == ("PATCH", f"/v2/instances/{twin_id}"))[2]["user_data"]))
        assert envelope["vpc_ip"] == fake.instances[twin_id].internal_ip
        assert envelope["control_plane"] == "http://10.1.96.4:8000"
