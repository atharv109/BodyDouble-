"""B3 groundwork: the t1_fallback post-restore path (run-13 T1b, driven by the
control plane). After the restore call the service: waits for the restore to
finish, re-patches user_data (the restore reverts it to the snapshot's
cloud-init — a stale registration token otherwise), then re-inserts the ISO
(the restore empties the CD drive while the API still reports isomounted;
runs 8-12 failed without the detach + attach).
"""
from __future__ import annotations

import pytest

from contracts.models import CaseState
from contracts.vultr import FakeVultr, VultrError

from backend.service import CaseService

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
