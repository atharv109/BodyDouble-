"""Deterministic Investigator used until the forensics worker is integrated."""
from __future__ import annotations

import hashlib

from contracts.agent import Report, TimelineEntry
from contracts.models import (
    ActionKind,
    Evidence,
    Finding,
    Severity,
    Step,
    StepKind,
    ToolCall,
    ToolName,
)


class ScriptedInvestigator:
    async def investigate(self, case, runner, recorder) -> Report:
        step = Step(
            id=f"{case.id}-step-001", case_id=case.id, seq=1,
            kind=StepKind.detonate, tool=ToolName.detonate,
            args={"path": "/opt/shop/beacon.sh"},
            rationale="Observe the suspicious beacon without network access.", code="",
        )
        await recorder.step_started(step)
        result = await runner.run(ToolCall(
            job_id=f"{case.id}-job-001", case_id=case.id,
            tool=ToolName.detonate, args=step.args,
        ))
        step.code, step.stdout, step.stderr = result.code, result.stdout, result.stderr
        step.exit_code, step.duration_ms = result.exit_code, result.duration_ms
        await recorder.step_finished(step)

        excerpt = "beacon resolves c2.example.invalid; network denied"
        evidence = Evidence(
            id=f"{case.id}-ev-002", case_id=case.id, step_id=step.id,
            path="/opt/shop/beacon.sh", sha256=hashlib.sha256(excerpt.encode()).hexdigest(),
            excerpt=excerpt,
        )
        await recorder.add_evidence(evidence)
        dns = Evidence(
            id=f"{case.id}-ev-003", case_id=case.id, step_id=step.id,
            path="dns:c2.example.invalid",
            sha256=hashlib.sha256(b"c2.example.invalid").hexdigest(),
            excerpt="DNS query captured by the no-network sinkhole",
        )
        await recorder.add_evidence(dns)
        await recorder.dns_captured(step.id, "c2.example.invalid", "0.0.0.0", dns.id)
        finding = Finding(
            id=f"{case.id}-fd-001", case_id=case.id,
            title="Beacon attempted command-and-control lookup",
            severity=Severity.high, mitre_id="T1071.004",
            summary="The copied script attempted DNS resolution while isolated.",
            evidence_ids=[evidence.id, dns.id],
        )
        await recorder.add_finding(finding)
        return Report(
            summary="A persistent beacon was found and safely observed in the sealed twin.",
            timeline=[TimelineEntry(ts="unknown", what=finding.title,
                                    evidence_ids=finding.evidence_ids)],
            ranked_actions=[ActionKind.quarantine_firewall, ActionKind.stop_instance],
        )
