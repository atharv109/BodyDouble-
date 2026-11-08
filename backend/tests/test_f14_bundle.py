from __future__ import annotations

import io
import json
import zipfile

import pytest

from contracts.hashing import verify_chain
from contracts.models import LogEntry


@pytest.mark.asyncio
async def test_bundle_contains_snapshot_hashes_log_and_report(client, human):
    run = await client.post("/dev/fake-case", headers=human, json={})
    assert run.status_code == 201, run.text
    case = run.json()

    response = await client.get(f"/cases/{case['id']}/bundle", headers=human)
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/zip"
    with zipfile.ZipFile(io.BytesIO(response.content)) as bundle:
        assert set(bundle.namelist()) == {
            "snapshot_id.txt", "file_hashes.json", "case_log.json", "report.json",
        }
        assert bundle.read("snapshot_id.txt").decode().strip() == case["snapshot_id"]
        hashes = json.loads(bundle.read("file_hashes.json"))
        assert hashes and all({"id", "path", "sha256"} <= item.keys()
                              for item in hashes)
        report = json.loads(bundle.read("report.json"))
        assert report["summary"] and report["timeline"]
        entries = [LogEntry.model_validate(item)
                   for item in json.loads(bundle.read("case_log.json"))]
        assert verify_chain(entries) is None
