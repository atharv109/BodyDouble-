"""Security review item 3 (orchestrator option a): the real InvestigatorImpl mints
case-scoped ids, so two real cases recorded into ONE control-plane database keep
disjoint steps/evidence/findings/jobs. Unscoped "step-01"/"ev-001" made the second
case collide with the first (IntegrityError) or attach to the first case's rows; and
the investigator's evidence must start after the control plane's snapshot record."""
from __future__ import annotations

import json
from datetime import datetime, timezone

from sqlalchemy import select

from bd_forensics.investigator import REQUIRED_TRIAGE, InvestigatorImpl
from contracts.models import Artifact, Case, Evidence, ToolCall, ToolResult
from contracts.vultr import FakeVultr

from backend.config import test_settings as make_test_settings
from backend.db import EvidenceRow, FindingRow, StepRow
from backend.recorder import DbCaseRecorder
from backend.state import build_state


class ScriptedModel:
    """Planner: one extract, then done. Analyst: one finding citing the evidence id
    WITHOUT the case prefix (models do that). Reporter: a summary."""

    def __init__(self) -> None:
        self.replies = [
            json.dumps({"tool": "extract", "args": {"path": "/etc/cron.d/x"},
                        "rationale": "read the cron entry", "done": False}),
            json.dumps({"done": True}),
            json.dumps({"findings": [{"title": "cron persistence", "severity": "high",
                                      "summary": "/etc/cron.d/x", "evidence_ids": ["ev-002"]}],
                        "timeline": [{"ts": "unknown", "what": "cron written",
                                      "evidence_ids": ["ev-002"]}]}),
            json.dumps({"summary": "one finding", "ranked_actions": []}),
        ]

    async def chat(self, _messages) -> str:
        return self.replies.pop(0)


class Runner:
    def __init__(self) -> None:
        self.job_ids: list[str] = []

    async def run(self, call: ToolCall) -> ToolResult:
        self.job_ids.append(call.job_id)
        artifacts = ([Artifact(path="/etc/cron.d/x", sha256="ab" * 32, excerpt="* * * * * root /x")]
                     if call.tool.value == "extract" else [])
        return ToolResult(job_id=call.job_id, code="", stdout=f"{call.tool.value} ok",
                          stderr="", exit_code=0, duration_ms=1, artifacts=artifacts)


def _case(case_id: str) -> Case:
    return Case(id=case_id, instance_id="i-1", instance_label="shop-prod",
                reason="alert", created_at=datetime.now(timezone.utc))


async def test_two_real_cases_share_one_database_without_id_collisions(tmp_path):
    settings = make_test_settings(f"sqlite:///{(tmp_path / 'two.db').as_posix()}")
    state = build_state(settings, vultr=FakeVultr())
    reports, runners = {}, {}
    for case_id in ("case-0001", "case-0002"):
        # the snapshot record first, through the control plane's own id path, exactly
        # as _snapshot_phase does before the investigator starts ("<case>-ev-001")
        state.service._add_evidence(Evidence(
            id=state.service._next_id(EvidenceRow, case_id, "ev"), case_id=case_id,
            step_id=None, path="snapshot:snap-1", sha256="cd" * 32, excerpt="snapshot"))
        runners[case_id] = Runner()
        reports[case_id] = await InvestigatorImpl(ScriptedModel()).investigate(
            _case(case_id), runners[case_id], DbCaseRecorder(state.sf, state.log))

    with state.sf() as s:
        for case_id in ("case-0001", "case-0002"):
            steps = s.execute(select(StepRow).where(StepRow.case_id == case_id)).scalars().all()
            evidence = s.execute(
                select(EvidenceRow).where(EvidenceRow.case_id == case_id)).scalars().all()
            findings = s.execute(
                select(FindingRow).where(FindingRow.case_id == case_id)).scalars().all()
            assert len(steps) == 1 + len(REQUIRED_TRIAGE)  # extract + code-run triage
            assert all(row.id.startswith(f"{case_id}-step-") for row in steps)
            # snapshot evidence + the investigator's own, which starts AFTER it
            assert sorted(row.id for row in evidence) == [f"{case_id}-ev-001", f"{case_id}-ev-002"]
            assert len(findings) == 1 and findings[0].id == f"{case_id}-finding-001"
            # the prefix-less "ev-002" the model cited resolved to THIS case's evidence
            assert list(findings[0].evidence_ids) == [f"{case_id}-ev-002"]
            assert all(j.startswith(f"{case_id}-job-") for j in runners[case_id].job_ids)
            assert reports[case_id].timeline[0].evidence_ids == [f"{case_id}-ev-002"]
