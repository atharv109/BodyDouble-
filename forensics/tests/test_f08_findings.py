"""F8: evidence-linked findings, code severity, and timeline."""
from __future__ import annotations

import json

import pytest

from bd_forensics.investigator import InvestigatorImpl
from conftest import FakeRecorder, LocalRunner, StubModel, VICTIM, make_case, prop


PATHS = [
    "/etc/cron.d/bdrv",
    "/root/.ssh/authorized_keys",
    "/usr/bin/top",
    "/usr/local/bin/.bdrv",
    "/var/backups/notes-to-ai.txt",
]


def analyst_reply(evidence_ids: list[str]) -> str:
    findings = [
        {"title": f"indicator {i}", "severity": "medium", "mitre_id": None,
         "summary": path, "evidence_ids": [evidence_ids[i - 1]]}
        for i, path in enumerate(PATHS, 1)
    ]
    # This model-invented evidence reference must be dropped by code.
    findings.append({"title": "hallucinated", "severity": "critical", "summary": "bad",
                     "evidence_ids": ["ev-does-not-exist"]})
    return json.dumps({
        "findings": findings,
        "timeline": [
            {"ts": "unknown", "what": path, "evidence_ids": [evidence_ids[i]]}
            for i, path in enumerate(PATHS)
        ],
    })


@pytest.mark.asyncio
async def test_victim_run_yields_five_evidence_linked_findings_and_timeline() -> None:
    planner = [prop("extract", {"path": path}, f"collect {path}") for path in PATHS]
    planner.append(prop(done=True))
    model = StubModel(planner + [
        analyst_reply([f"ev-{i:03d}" for i in range(1, 6)]),
        json.dumps({"summary": "Five planted indicators confirmed.",
                    "ranked_actions": ["quarantine_firewall", "invented_action"]}),
    ])
    recorder = FakeRecorder()

    report = await InvestigatorImpl(model).investigate(
        make_case(), LocalRunner(VICTIM), recorder
    )

    assert len(recorder.findings) == 5
    known = {ev.id for ev in recorder.evidence}
    assert all(f.evidence_ids and set(f.evidence_ids) <= known for f in recorder.findings)
    assert "hallucinated" not in {f.title for f in recorder.findings}
    by_path = {f.summary: f for f in recorder.findings}
    assert by_path["/etc/cron.d/bdrv"].severity.value == "critical"
    assert by_path["/root/.ssh/authorized_keys"].severity.value == "critical"
    assert len(report.timeline) == 5
    assert report.summary == "Five planted indicators confirmed."
    assert [a.value for a in report.ranked_actions] == ["quarantine_firewall"]
