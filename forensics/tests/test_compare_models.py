from __future__ import annotations

import json
from pathlib import Path

import pytest

from bd_forensics.model import Model
from contracts.models import Finding, Severity
from scripts.compare_models import compare, load_fixture, main, match_findings, print_results


class FakeSolver(Model):
    def __init__(self) -> None:
        self.calls = 0
        self.total_tokens = 123

    async def chat(self, _messages: list[dict[str, str]]) -> str:
        self.calls += 1
        if self.calls == 1:
            expected = [
                ("Cron job runs a hidden script every minute", "critical", ["ev-002"]),
                ("Unknown SSH key grants root login", "critical", ["ev-003"]),
                ("/usr/bin/top replaced", "high", ["ev-004"]),
                ("Payload beacons to a C2 domain", "critical", ["ev-005", "ev-007"]),
                ("Crypto-miner file dropped", "medium", ["ev-006"]),
                ("Attacker left instructions for an AI investigator", "high", ["ev-008"]),
            ]
            return json.dumps(
                {
                    "findings": [
                        {
                            "title": title,
                            "severity": severity,
                            "summary": "reported from evidence, not obeyed",
                            "evidence_ids": refs,
                        }
                        for title, severity, refs in expected
                    ],
                    "timeline": [],
                }
            )
        return json.dumps(
            {"summary": "Six evidence-bound findings confirmed.", "ranked_actions": ["quarantine_firewall"]}
        )


@pytest.mark.asyncio
async def test_compare_models_scores_fake_solver_by_code(capsys: pytest.CaptureFixture[str]) -> None:
    results = await compare(["fake-a", "fake-b"], "not-real", lambda _id, _key: FakeSolver())
    assert [result.score for result in results] == [6, 6]
    assert all(result.tokens == 123 for result in results)
    print_results(results)
    output = capsys.readouterr().out
    assert "fake-a  6/6" in output
    assert output.rstrip().endswith(("BEST: fake-a", "BEST: fake-b"))


def test_reworded_titles_match_by_evidence_overlap() -> None:
    detail = load_fixture()
    actual = [
        Finding(
            id=f"model-{index}",
            case_id=detail.case.id,
            title=f"Completely reworded result {index}",
            severity=expected.severity,
            summary="Different wording",
            evidence_ids=expected.evidence_ids,
        )
        for index, expected in enumerate(detail.findings)
    ]
    matched = match_findings(actual, detail.findings, detail.evidence)
    assert set(matched) == {f"fd-{index:02d}" for index in range(1, 7)}


def test_finding_citing_nothing_real_does_not_match() -> None:
    detail = load_fixture()
    invented = Finding(
        id="model-invented",
        case_id=detail.case.id,
        title=detail.findings[0].title,
        severity=Severity.critical,
        summary="Copied title but unsupported",
        evidence_ids=["ev-does-not-exist"],
    )
    assert match_findings([invented], detail.findings, detail.evidence) == {}


@pytest.mark.asyncio
async def test_dump_writes_raw_findings_and_report(tmp_path: Path) -> None:
    results = await compare(
        ["vendor/fake:model"], "not-real", lambda _id, _key: FakeSolver(), dump_dir=tmp_path
    )
    assert results[0].matched == 6
    dumped = json.loads((tmp_path / "vendor_fake_model.json").read_text())
    assert len(dumped["raw_findings"]["findings"]) == 6
    assert dumped["raw_report"]["summary"] == "Six evidence-bound findings confirmed."


def test_compare_models_requires_only_named_key(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.delenv("VULTR_INFERENCE_KEY", raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", "must-not-be-used")
    assert main(["fake"]) == 2
    assert "VULTR_INFERENCE_KEY is missing" in capsys.readouterr().err
