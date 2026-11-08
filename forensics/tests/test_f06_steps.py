"""F6: planner proposes triage steps from the fixed tool list; each step is
code run against the mounted disk; budgets from contracts.agent enforced.

Run against demo/victim/: every step must be recorded with code, stdout,
exit code and duration.
"""
from __future__ import annotations

import hashlib

from contracts.agent import CASE_TIME_BUDGET_S, MAX_DETONATIONS, MAX_STEPS
from contracts.models import StepKind, ToolName

from bd_forensics.indicators import INDICATORS, C2_DOMAIN
from bd_forensics.investigator import InvestigatorImpl

from conftest import (
    CLEAN,
    VICTIM,
    CountingRunner,
    FakeClock,
    StubModel,
    prop,
)

# the full triage sweep the (stubbed) planner proposes on the demo victim
TRIAGE_PLAN = [
    prop("os_facts", rationale="orient: what is this box"),
    prop("persistence_scan", rationale="look for cron/systemd persistence"),
    prop("auth_scan", rationale="check keys and recent logins"),
    prop("recent_files", rationale="see what changed lately"),
    prop("binary_integrity", rationale="verify packaged binaries"),
    prop("listener_config", rationale="see what listens"),
    prop("extract", {"path": "/usr/local/bin/.bdrv"}, "grab the script the cron entry runs"),
    prop("extract", {"path": "/var/backups/notes-to-ai.txt"}, "read the odd backup note"),
]


async def test_every_step_recorded_with_code_output_exit_duration(case, recorder, victim_runner) -> None:
    model = StubModel(TRIAGE_PLAN)
    await InvestigatorImpl(model).investigate(case, victim_runner, recorder)
    assert len(recorder.finished) == len(TRIAGE_PLAN)
    for step in recorder.finished:
        assert step.code, f"{step.tool} ran without code"
        assert step.exit_code == 0, f"{step.tool} failed: {step.stderr}"
        assert isinstance(step.duration_ms, int) and step.duration_ms >= 0
        assert step.stdout, f"{step.tool} produced no stdout"
        assert step.kind is StepKind.triage
        assert step.rationale


async def test_steps_read_the_victim_disk(case, recorder, victim_runner) -> None:
    model = StubModel(TRIAGE_PLAN)
    await InvestigatorImpl(model).investigate(case, victim_runner, recorder)
    out = {s.tool: s.stdout for s in recorder.finished}

    assert "Debian" in out[ToolName.os_facts]
    assert INDICATORS["/etc/cron.d/bdrv"] in out[ToolName.persistence_scan]
    assert "ops-backup@bodydouble-demo" in out[ToolName.auth_scan]
    assert "Accepted publickey for root" in out[ToolName.auth_scan]
    assert "MISMATCH usr/bin/top" in out[ToolName.binary_integrity]
    assert out[ToolName.recent_files].strip()  # list of recently changed files


async def test_extract_creates_hashed_evidence(case, recorder, victim_runner) -> None:
    model = StubModel(TRIAGE_PLAN)
    await InvestigatorImpl(model).investigate(case, victim_runner, recorder)

    ev_paths = {e.path for e in recorder.evidence}
    assert ev_paths == {"/usr/local/bin/.bdrv", "/var/backups/notes-to-ai.txt"}
    bdrv_ev = next(e for e in recorder.evidence if e.path == "/usr/local/bin/.bdrv")
    on_disk = hashlib.sha256((VICTIM / "usr/local/bin/.bdrv").read_bytes()).hexdigest()
    assert bdrv_ev.sha256 == on_disk
    assert C2_DOMAIN in bdrv_ev.excerpt
    assert bdrv_ev.step_id == recorder.finished[-2].id


async def test_step_budget_caps_at_max_steps(case, recorder) -> None:
    model = StubModel([prop("os_facts")] * 60)  # never says done
    counting = CountingRunner()
    await InvestigatorImpl(model).investigate(case, counting, recorder)
    assert len(counting.calls) == MAX_STEPS == 25


async def test_detonation_budget_is_six(case, recorder) -> None:
    model = StubModel(
        [prop("detonate", {"path": "/usr/local/bin/.bdrv"})] * MAX_DETONATIONS
        + [prop("os_facts")] * 60
    )
    counting = CountingRunner()
    await InvestigatorImpl(model).investigate(case, counting, recorder)
    det_calls = [c for c in counting.calls if c.tool == ToolName.detonate]
    assert len(det_calls) == MAX_DETONATIONS == 6
    assert len(counting.calls) == MAX_STEPS
    det_steps = [s for s in recorder.finished if s.tool == ToolName.detonate]
    assert det_steps and all(s.kind is StepKind.detonate for s in det_steps)


async def test_time_budget_caps_the_case(case, recorder) -> None:
    model = StubModel([prop("os_facts")] * 100)
    counting = CountingRunner()
    await InvestigatorImpl(model, clock=FakeClock(step_s=100.0)).investigate(case, counting, recorder)
    # clock advances 100 s per call: iterations 1-5 run (elapsed 100..500 s),
    # iteration 6 sees elapsed 600 s and stops before running
    assert len(counting.calls) == 5
    assert CASE_TIME_BUDGET_S == 600


async def test_invalid_and_unsafe_proposals_never_run(case, recorder) -> None:
    model = StubModel(
        [
            '{"tool": "rm_dash_rf", "args": {}, "rationale": "clean up"}',
            '{"tool": "extract", "args": {}, "rationale": "no path"}',
            '{"tool": "extract", "args": {"path": "../../etc/shadow"}, "rationale": "escape"}',
            prop("extract", {"path": "/etc/passwd"}, "a normal read"),
        ]
    )
    counting = CountingRunner()
    await InvestigatorImpl(model).investigate(case, counting, recorder)
    assert len(counting.calls) == 1
    assert counting.calls[0].tool is ToolName.extract
    assert counting.calls[0].args["path"] == "/etc/passwd"


async def test_run_aborts_after_consecutive_bad_proposals(case, recorder) -> None:
    model = StubModel(["not json at all"] * 10)
    counting = CountingRunner()
    await InvestigatorImpl(model).investigate(case, counting, recorder)
    assert counting.calls == []
    assert len(model.calls) == 5
