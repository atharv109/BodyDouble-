"""The Investigator (contracts.agent seam): the model plans and explains,
code executes and decides.

The loop: planner proposes one tool at a time from the fixed list -> code
validates the proposal and the budgets -> the runner (backend StepRunner;
tests use LocalRunner) executes it on the twin -> every step is recorded
with code, stdout, exit code and duration -> artifacts become hashed
evidence. The analyst and reporter roles (F8) attach after each step and
at the end.

Budgets from contracts.agent, enforced here in code: MAX_STEPS triage+
detonation steps, MAX_DETONATIONS detonations, CASE_TIME_BUDGET_S wall
clock, and a cap on consecutive invalid planner proposals.
"""
from __future__ import annotations

import hashlib
import time
from typing import Callable

from contracts import agent as contracts_agent
from contracts.agent import Report
from contracts.models import (
    Case,
    Evidence,
    Step,
    StepKind,
    ToolCall,
    ToolName,
    ToolResult,
)

from .injection import wrap_excerpt
from .model import Model
from .planner import plan_next_step
from .tools import valid_args

MAX_STEPS = contracts_agent.MAX_STEPS
MAX_DETONATIONS = contracts_agent.MAX_DETONATIONS
CASE_TIME_BUDGET_S = contracts_agent.CASE_TIME_BUDGET_S
MAX_INVALID_PROPOSALS = 5

SINKHOLE_IP = "0.0.0.0"  # the fake resolver answers every lookup with this

MAX_CONTEXT_STEPS = 12  # how much recent output the planner sees next turn


class InvestigatorImpl:
    def __init__(self, model: Model, clock: Callable[[], float] = time.monotonic) -> None:
        self.model = model
        self._clock = clock

    async def investigate(self, case: Case, runner, recorder) -> Report:
        t0 = self._clock()
        steps = detonations = invalid = 0
        evidence: list[Evidence] = []
        history: list[str] = [f"case reason: {case.reason}"]

        while steps < MAX_STEPS:
            elapsed = self._clock() - t0
            if elapsed >= CASE_TIME_BUDGET_S:
                break
            proposal = await plan_next_step(self.model, "\n\n".join(history[-(2 * MAX_CONTEXT_STEPS):]))
            if proposal is None:
                invalid += 1
                if invalid >= MAX_INVALID_PROPOSALS:
                    break
                continue
            if proposal.done:
                break
            if not valid_args(proposal.tool, proposal.args):
                invalid += 1
                if invalid >= MAX_INVALID_PROPOSALS:
                    break
                continue
            if proposal.tool == ToolName.detonate:
                if detonations >= MAX_DETONATIONS:
                    invalid += 1
                    if invalid >= MAX_INVALID_PROPOSALS:
                        break
                    continue
                detonations += 1
            invalid = 0

            seq = steps + 1
            job = ToolCall(
                job_id=f"job-{seq:02d}", case_id=case.id, tool=proposal.tool, args=proposal.args
            )
            step = Step(
                id=f"step-{seq:02d}",
                case_id=case.id,
                seq=seq,
                kind=StepKind.detonate if proposal.tool == ToolName.detonate else StepKind.triage,
                tool=proposal.tool,
                args=proposal.args,
                rationale=proposal.rationale,
                code="",
            )
            await recorder.step_started(step)
            result = await runner.run(job)
            step.code = result.code
            step.stdout = result.stdout
            step.stderr = result.stderr
            step.exit_code = result.exit_code
            step.duration_ms = result.duration_ms
            await recorder.step_finished(step)
            steps += 1

            history.append(f"step {seq} ({proposal.tool}): {proposal.rationale}")
            history.append(wrap_excerpt(f"{proposal.tool} output", result.stdout))

            for artifact in result.artifacts:
                ev = Evidence(
                    id=f"ev-{len(evidence) + 1:03d}",
                    case_id=case.id,
                    step_id=step.id,
                    path=artifact.path,
                    sha256=artifact.sha256,
                    excerpt=artifact.excerpt,
                )
                await recorder.add_evidence(ev)
                evidence.append(ev)
            for query in result.dns_queries:
                ev = Evidence(
                    id=f"ev-{len(evidence) + 1:03d}",
                    case_id=case.id,
                    step_id=step.id,
                    path=f"dns:{query}",
                    sha256=hashlib.sha256(query.encode()).hexdigest(),
                    excerpt=f"DNS lookup of {query} attempted from inside the detonation sandbox; answered by the sinkhole.",
                )
                await recorder.add_evidence(ev)
                evidence.append(ev)
                await recorder.dns_captured(step.id, query, SINKHOLE_IP, ev.id)

        return Report(summary="", timeline=[], ranked_actions=[])
