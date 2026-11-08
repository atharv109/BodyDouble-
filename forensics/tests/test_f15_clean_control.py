"""F15: uncompromised twin control produces no findings."""
from __future__ import annotations

import hashlib

import pytest

from bd_forensics.indicators import INDICATORS
from bd_forensics.investigator import InvestigatorImpl
from conftest import CLEAN, FakeRecorder, LocalRunner, StubModel, make_case, prop


@pytest.mark.asyncio
async def test_same_pipeline_reports_zero_findings_on_clean_control() -> None:
    tools = [
        "os_facts", "persistence_scan", "auth_scan", "recent_files",
        "binary_integrity", "listener_config",
    ]
    model = StubModel([prop(tool, rationale=f"clean control {tool}") for tool in tools]
                      + [prop(done=True)])
    recorder = FakeRecorder()

    report = await InvestigatorImpl(model).investigate(
        make_case("clean-case"), LocalRunner(CLEAN), recorder
    )

    assert len(recorder.finished) == len(tools)
    assert recorder.evidence == []
    assert recorder.findings == []
    assert report.summary == "No forensic findings."
    assert report.timeline == []


def test_clean_tree_matches_server_baseline_without_planted_indicators() -> None:
    assert (CLEAN / "etc/hostname").read_text().strip() == "shop-prod"
    assert "Debian" in (CLEAN / "etc/os-release").read_text()
    for planted_path, marker in INDICATORS.items():
        candidate = CLEAN / planted_path.lstrip("/")
        if candidate.exists():
            assert marker not in candidate.read_text()
    top = (CLEAN / "usr/bin/top").read_bytes()
    recorded = (CLEAN / "var/lib/dpkg/info/procps.md5sums").read_text().split()[0]
    assert hashlib.md5(top).hexdigest() == recorded
