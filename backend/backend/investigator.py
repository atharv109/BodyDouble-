"""Deterministic replay of the recorded FakeVultr investigation story."""
from __future__ import annotations

import hashlib

from contracts.agent import Report, TimelineEntry
from contracts.fixtures.make_fixture import FINDINGS, STEPS
from contracts.models import ActionKind, Evidence, Finding, Step, StepKind, ToolCall, ToolName


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class ScriptedInvestigator:
    def __init__(self, fixture_ids: bool = False):
        self.fixture_ids = fixture_ids

    def _id(self, case_id: str, kind: str, seq: int) -> str:
        if self.fixture_ids:
            width = 2 if kind in {"step", "fd"} else 3
            return f"{kind}-{seq:0{width}d}"
        return f"{case_id}-{kind}-{seq:03d}"

    async def investigate(self, case, runner, recorder) -> Report:
        evidence_by_path: dict[str, str] = {}
        evidence_seq = 2  # snapshot evidence is item 1
        for seq, (tool, args, rationale, code, stdout, artifacts, dns) in enumerate(
            STEPS, start=1
        ):
            step_id = self._id(case.id, "step", seq)
            step = Step(
                id=step_id, case_id=case.id, seq=seq,
                kind=StepKind.detonate if tool is ToolName.detonate else StepKind.triage,
                tool=tool, args=args, rationale=rationale, code=code,
            )
            await recorder.step_started(step)
            result = await runner.run(ToolCall(
                job_id=f"{case.id}-job-{seq:03d}", case_id=case.id,
                tool=tool, args=args,
            ))
            step.stdout, step.stderr = stdout, result.stderr
            step.exit_code, step.duration_ms = result.exit_code, 800 + 137 * seq
            await recorder.step_finished(step)

            for path, excerpt, injection in artifacts:
                evidence_id = self._id(case.id, "ev", evidence_seq)
                evidence_seq += 1
                await recorder.add_evidence(Evidence(
                    id=evidence_id, case_id=case.id, step_id=step_id,
                    path=path, sha256=_sha(excerpt), excerpt=excerpt,
                    injection_flag=injection,
                ))
                evidence_by_path[path] = evidence_id
            if dns:
                path = f"dns:{dns}"
                evidence_id = self._id(case.id, "ev", evidence_seq)
                evidence_seq += 1
                await recorder.add_evidence(Evidence(
                    id=evidence_id, case_id=case.id, step_id=step_id,
                    path=path, sha256=_sha(dns),
                    excerpt=f"A? {dns} -> 10.255.255.1",
                ))
                evidence_by_path[path] = evidence_id
                await recorder.dns_captured(step_id, dns, "10.255.255.1", evidence_id)

        findings: list[Finding] = []
        for seq, (title, severity, mitre, summary, paths) in enumerate(FINDINGS, start=1):
            finding = Finding(
                id=self._id(case.id, "fd", seq), case_id=case.id,
                title=title, severity=severity, mitre_id=mitre, summary=summary,
                evidence_ids=[evidence_by_path[path] for path in paths],
            )
            await recorder.add_finding(finding)
            findings.append(finding)
        return Report(
            summary="Six findings identified across persistence, access, tampering, "
                    "command-and-control, mining, and prompt injection.",
            timeline=[TimelineEntry(ts="unknown", what=f.title,
                                    evidence_ids=f.evidence_ids) for f in findings],
            ranked_actions=list(ActionKind),
            rogue_ssh_keys=["ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIFakeKeyForDemo0000 x@kali"],
            secrets_found=["/var/www/shop/.env"],
        )
