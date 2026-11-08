"""Seam between backend/ (control plane) and forensics/ (agent loop + twin tools).

    backend calls   Investigator.investigate(case, runner, recorder) -> Report
    backend gives   StepRunner   (queues a ToolCall to the twin over /twin/jobs, awaits ToolResult)
    backend gives   CaseRecorder (persists rows, appends hash-chained log, emits SSE)
    backend builds  the containment Action menu from Report + findings (F9) -- code, not model.

All model calls go to Vultr Serverless Inference (OpenAI-compatible).
"""
from __future__ import annotations

from typing import Protocol

from pydantic import BaseModel, Field

from .models import ActionKind, Case, Evidence, Finding, Step, ToolCall, ToolResult

INFERENCE_BASE_URL = "https://api.vultrinference.com/v1"

# Guardrails in code (PRD "Guardrails in code")
MAX_STEPS = 25
MAX_DETONATIONS = 6
CASE_TIME_BUDGET_S = 600
EXCERPT_MAX_CHARS = 2000


class StepRunner(Protocol):
    async def run(self, call: ToolCall) -> ToolResult: ...


class CaseRecorder(Protocol):
    async def step_started(self, step: Step) -> None: ...
    async def step_finished(self, step: Step) -> None: ...
    async def add_evidence(self, evidence: Evidence) -> None: ...
    async def dns_captured(self, step_id: str, query: str, answered_with: str, evidence_id: str) -> None: ...
    async def add_finding(self, finding: Finding) -> None: ...  # backend rejects unknown evidence ids


class TimelineEntry(BaseModel):
    ts: str  # ISO-8601 or "unknown"
    what: str
    evidence_ids: list[str] = Field(default_factory=list)


class Report(BaseModel):
    summary: str  # plain English, reporter output
    timeline: list[TimelineEntry]
    ranked_actions: list[ActionKind]  # model may rank menu kinds, never invent new ones
    rogue_ssh_keys: list[str] = Field(default_factory=list)  # authorized_keys lines (code-derived)
    secrets_found: list[str] = Field(default_factory=list)  # paths only, never values


class Investigator(Protocol):
    async def investigate(self, case: Case, runner: StepRunner, recorder: CaseRecorder) -> Report: ...
