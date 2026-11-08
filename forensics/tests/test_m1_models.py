from __future__ import annotations

import json

import pytest

from bd_forensics.investigator import InvestigatorImpl
from conftest import FakeRecorder, LocalRunner, StubModel, VICTIM, make_case, prop


@pytest.mark.asyncio
async def test_investigator_routes_planning_and_solver_roles() -> None:
    planner = StubModel([prop("extract", {"path": "/usr/bin/top"}, "collect top"), prop(done=True)])
    solver = StubModel(
        [
            json.dumps(
                {
                    "findings": [
                        {
                            "title": "top replaced",
                            "severity": "high",
                            "summary": "checksum mismatch",
                            "evidence_ids": ["ev-001"],
                        }
                    ],
                    "timeline": [],
                }
            ),
            json.dumps({"summary": "Compromise confirmed.", "ranked_actions": []}),
        ]
    )

    await InvestigatorImpl(planner, solver).investigate(
        make_case(), LocalRunner(VICTIM), FakeRecorder()
    )

    assert len(planner.calls) == 2
    assert all("Choose one tool" in call[0]["content"] for call in planner.calls)
    assert len(solver.calls) == 2
    assert "forensic analyst" in solver.calls[0][0]["content"]
    assert "forensic reporter" in solver.calls[1][0]["content"]


def test_single_model_constructor_still_uses_one_model() -> None:
    model = StubModel()
    investigator = InvestigatorImpl(model)
    assert investigator.planner_model is model
    assert investigator.solver_model is model
