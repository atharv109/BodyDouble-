from __future__ import annotations

import sys
from types import SimpleNamespace

from contracts.agent import Report
from contracts.vultr import FakeVultr

from backend.config import test_settings as make_test_settings
from backend.service import build_real_investigator
from backend.state import build_state


class FakeInvestigator:
    def __init__(self, calls: list[str], name: str):
        self.calls = calls
        self.name = name

    async def investigate(self, case, runner, recorder):
        self.calls.append(self.name)
        return Report(summary=f"{self.name} report", timeline=[], ranked_actions=[],
                      rogue_ssh_keys=[], secrets_found=[])


async def _run_investigation(state):
    case = await state.service.open_case("inst-shop-prod", "investigate")
    await state.service.run_case(case.id, force_full=True, auto_close=False)
    return state.service.model(case.id)


async def test_inference_key_selects_real_two_model_investigator(
        tmp_path, monkeypatch):
    settings = make_test_settings(f"sqlite:///{(tmp_path / 'real-ai.db').as_posix()}")
    settings.inference_key = "fake-key-never-sent"
    settings.model_planner = "fake-planner"
    settings.model_solver = "fake-solver"
    settings.vultr_api_key = "fake-vultr-key"
    settings.operator_password = "correct-horse-battery"
    settings.app_secret = "m" * 64
    settings.investigation_vpc_id = "vpc-shared"
    settings.investigation_vpc_subnet = "10.77.0.0/24"
    settings.control_url = "http://10.77.0.1:8000"
    calls = []
    monkeypatch.setattr("backend.service.build_real_investigator",
                        lambda configured: FakeInvestigator(calls, "real"))
    state = build_state(settings, vultr=FakeVultr())
    try:
        case = await _run_investigation(state)
        assert case.state.value == "reported"
        assert calls == ["real"]
    finally:
        for task in state.fake_twin_tasks.values():
            task.cancel()
        state.close()


def test_real_factory_builds_distinct_planner_and_solver_models(monkeypatch):
    configured = []

    class FakeModel:
        def __init__(self, api_key, model):
            configured.append((api_key, model))

    class FakeRealInvestigator:
        def __init__(self, **kwargs):
            self.kwargs = kwargs

    monkeypatch.setitem(sys.modules, "bd_forensics.investigator", SimpleNamespace(
        InvestigatorImpl=FakeRealInvestigator))
    monkeypatch.setitem(sys.modules, "bd_forensics.model", SimpleNamespace(
        OpenAIModel=FakeModel))
    settings = make_test_settings("sqlite://")
    settings.inference_key = "fake-key-never-sent"
    settings.model_planner = "planner-id"
    settings.model_solver = "solver-id"
    investigator = build_real_investigator(settings)
    assert configured == [
        ("fake-key-never-sent", "planner-id"),
        ("fake-key-never-sent", "solver-id"),
    ]
    assert set(investigator.kwargs) == {"planner", "solver"}
    assert investigator.kwargs["planner"] is not investigator.kwargs["solver"]


async def test_without_inference_key_keeps_scripted_investigator(
        tmp_path, monkeypatch):
    settings = make_test_settings(f"sqlite:///{(tmp_path / 'scripted.db').as_posix()}")
    calls = []
    monkeypatch.setattr("backend.service.ScriptedInvestigator",
                        lambda **_kwargs: FakeInvestigator(calls, "scripted"))
    monkeypatch.setattr(
        "backend.service.build_real_investigator",
        lambda _configured: (_ for _ in ()).throw(AssertionError("real investigator used")),
    )
    state = build_state(settings, vultr=FakeVultr())
    try:
        case = await _run_investigation(state)
        assert case.state.value == "reported"
        assert calls == ["scripted"]
    finally:
        for task in state.fake_twin_tasks.values():
            task.cancel()
        state.close()


def test_inference_key_requires_both_model_ids(tmp_path):
    for planner, solver in [(None, None), ("planner", None), (None, "solver")]:
        settings = make_test_settings(
            f"sqlite:///{(tmp_path / f'{planner}-{solver}.db').as_posix()}"
        )
        settings.inference_key = "fake-key-never-sent"
        settings.model_planner = planner
        settings.model_solver = solver
        try:
            build_state(settings, vultr=FakeVultr())
        except RuntimeError as error:
            assert "BD_MODEL_PLANNER and BD_MODEL_SOLVER" in str(error)
        else:
            raise AssertionError("startup accepted missing model configuration")
