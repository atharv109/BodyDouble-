"""Shared test doubles.

The model is always stubbed (no network, no keys). FakeRecorder and
LocalRunner are fakes of the backend's contracts.agent seams
(CaseRecorder, StepRunner): LocalRunner does the twin's job locally - it
builds the exact tool code and runs it against a disk tree
(demo/victim/ or demo/clean/), so pipeline tests exercise the real tools.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from contracts.models import Case, ToolCall, ToolResult

from bd_forensics.tools import execute

REPO = Path(__file__).resolve().parents[2]
VICTIM = REPO / "demo" / "victim"
CLEAN = REPO / "demo" / "clean"


def make_case(case_id: str = "case-1") -> Case:
    return Case(
        id=case_id,
        instance_id="i-12345",
        instance_label="shop-prod",
        reason="CPU at 100% overnight, unknown process",
        created_at=datetime.now(timezone.utc),
    )


def prop(tool: str | None = None, args: dict | None = None, rationale: str = "why", done: bool = False) -> str:
    """A planner reply as the model would emit it."""
    return json.dumps({"tool": tool, "args": args or {}, "rationale": rationale, "done": done})


class StubModel:
    """Scripted model: returns queued replies, then '{"done": true}'."""

    def __init__(self, replies: list[str] | None = None) -> None:
        self.replies = list(replies or [])
        self.calls: list[list[dict]] = []

    async def chat(self, messages: list[dict[str, str]]) -> str:
        self.calls.append(messages)
        if self.replies:
            return self.replies.pop(0)
        return '{"done": true}'


class FakeRecorder:
    """Fake of the backend CaseRecorder; records everything it is told."""

    def __init__(self) -> None:
        self.started: list[Case] = []
        self.finished: list = []
        self.evidence: list = []
        self.findings: list = []
        self.dns: list[tuple[str, str, str, str]] = []

    async def step_started(self, step) -> None:
        self.started.append(step)

    async def step_finished(self, step) -> None:
        self.finished.append(step)

    async def add_evidence(self, evidence) -> None:
        self.evidence.append(evidence)

    async def dns_captured(self, step_id: str, query: str, answered_with: str, evidence_id: str) -> None:
        self.dns.append((step_id, query, answered_with, evidence_id))

    async def add_finding(self, finding) -> None:
        self.findings.append(finding)


class LocalRunner:
    """Fake backend StepRunner doing the twin's job on this host: executes
    the real tool code against the mount and returns the ToolResult."""

    def __init__(self, mount: Path) -> None:
        self.mount = str(mount)
        self.results: list[ToolResult] = []

    async def run(self, call: ToolCall) -> ToolResult:
        result = execute(call, self.mount)
        self.results.append(result)
        return result


class CountingRunner:
    """Fake runner that never executes anything; counts calls (budget tests)."""

    def __init__(self) -> None:
        self.calls: list[ToolCall] = []

    async def run(self, call: ToolCall) -> ToolResult:
        self.calls.append(call)
        return ToolResult(
            job_id=call.job_id, code="# not run", stdout="stub", stderr="",
            exit_code=0, duration_ms=1,
        )


class FakeClock:
    """Monotonic-ish fake clock: advances by step_s on every call."""

    def __init__(self, step_s: float = 0.0) -> None:
        self.t = 0.0
        self.step_s = step_s

    def __call__(self) -> float:
        self.t += self.step_s
        return self.t


@pytest.fixture
def case() -> Case:
    return make_case()


@pytest.fixture
def recorder() -> FakeRecorder:
    return FakeRecorder()


@pytest.fixture
def victim_runner() -> LocalRunner:
    return LocalRunner(VICTIM)


@pytest.fixture
def clean_runner() -> LocalRunner:
    return LocalRunner(CLEAN)
