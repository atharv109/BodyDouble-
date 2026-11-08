"""DbCaseRecorder: contracts.agent.CaseRecorder — persists steps, evidence and
findings, appends the hash-chained case log and emits the SSE events. Findings
that cite evidence the case does not have are rejected (the analyst's
candidates are dropped by the investigation loop, never persisted)."""
from __future__ import annotations

from sqlalchemy import select

from contracts.events import DnsCaptured, FindingAdded, StepFinished, StepStarted
from contracts.models import Evidence, Finding, Step

from .db import EvidenceRow, FindingRow, StepRow


class DbCaseRecorder:
    def __init__(self, sf, log):
        self._sf = sf
        self._log = log

    # ------------------------------------------------------------- steps
    async def step_started(self, step: Step) -> None:
        with self._sf() as s:
            s.add(StepRow(**step.model_dump()))
            s.commit()
        self._log.append(step.case_id, "step_started", StepStarted(step=step))

    async def step_finished(self, step: Step) -> None:
        with self._sf() as s:
            row = s.get(StepRow, step.id)
            if row is None:
                raise LookupError(f"step_finished for unknown step {step.id}")
            row.code = step.code
            row.stdout, row.stderr = step.stdout, step.stderr
            row.exit_code, row.duration_ms = step.exit_code, step.duration_ms
            s.commit()
        self._log.append(step.case_id, "step_finished", StepFinished(step=step))

    # ------------------------------------------------------------- evidence
    async def add_evidence(self, evidence: Evidence) -> None:
        with self._sf() as s:
            s.add(EvidenceRow(**evidence.model_dump()))
            s.commit()
        self._log.append(evidence.case_id, "evidence_added",
                         evidence.model_dump(mode="json"))

    async def dns_captured(self, step_id: str, query: str, answered_with: str,
                           evidence_id: str) -> None:
        with self._sf() as s:
            ev = s.get(EvidenceRow, evidence_id)
        if ev is None:
            raise LookupError(f"dns_captured for unknown evidence {evidence_id}")
        self._log.append(ev.case_id, "dns_captured", DnsCaptured(
            case_id=ev.case_id, step_id=step_id, query=query,
            answered_with=answered_with, evidence_id=evidence_id))

    # ------------------------------------------------------------- findings
    async def add_finding(self, finding: Finding) -> None:
        with self._sf() as s:
            known = set(s.execute(select(EvidenceRow.id)
                                  .where(EvidenceRow.case_id == finding.case_id)).scalars())
        unknown = [e for e in finding.evidence_ids if e not in known]
        if unknown:
            raise ValueError(f"finding cites unknown evidence ids: {unknown}")
        with self._sf() as s:
            s.add(FindingRow(**finding.model_dump()))
            s.commit()
        self._log.append(finding.case_id, "finding_added", FindingAdded(finding=finding))
