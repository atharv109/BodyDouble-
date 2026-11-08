#!/usr/bin/env python3
"""Compare Vultr solver models against the recorded shop-prod evidence."""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from contracts.agent import Report
from contracts.models import CaseDetail, Evidence, Finding

from bd_forensics.analyst import analyze, report
from bd_forensics.model import Model, OpenAIModel


FIXTURE = Path(__file__).parents[2] / "contracts" / "fixtures" / "fake_case_detail.json"


@dataclass
class Result:
    model_id: str
    score: int
    findings: int
    latency_s: float
    tokens: int
    checks: str


def load_fixture() -> CaseDetail:
    return CaseDetail.model_validate_json(FIXTURE.read_text(encoding="utf-8"))


def normalized(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", value.casefold()).strip()


def match_findings(
    actual: list[Finding], expected: list[Finding], evidence: list[Evidence]
) -> dict[str, Finding]:
    paths = {ev.id: ev.path for ev in evidence}
    remaining = {item.id: item for item in expected}
    matched: dict[str, Finding] = {}
    for finding in actual:
        title_matches = [
            item for item in remaining.values() if normalized(item.title) == normalized(finding.title)
        ]
        candidates = title_matches
        if not candidates:
            cited_paths = {paths[ref] for ref in finding.evidence_ids if ref in paths}
            candidates = [
                item
                for item in remaining.values()
                if cited_paths
                and cited_paths.intersection(paths[ref] for ref in item.evidence_ids if ref in paths)
            ]
        if len(candidates) == 1:
            expected_item = candidates[0]
            matched[expected_item.id] = finding
            remaining.pop(expected_item.id)
    return matched


async def evaluate(model_id: str, model: Model, detail: CaseDetail) -> Result:
    started = time.perf_counter()
    findings, timeline = await analyze(model, detail.case.id, detail.evidence)
    solver_report = await report(model, detail.evidence, timeline)
    latency = time.perf_counter() - started

    known_ids = {ev.id for ev in detail.evidence}
    matched = match_findings(findings, detail.findings, detail.evidence)
    evidence_ok = all(f.evidence_ids and set(f.evidence_ids) <= known_ids for f in findings)
    complete = len(matched) == 6
    no_invented = len(findings) == 6 and len(matched) == len(findings)
    note = matched.get("fd-06")
    note_ok = note is not None and "ev-008" in note.evidence_ids and complete
    severity_ok = complete and all(
        matched[item.id].severity == item.severity for item in detail.findings
    )
    report_ok = isinstance(solver_report, Report) and bool(solver_report.summary.strip())
    checks_list = [report_ok, evidence_ok, complete, no_invented, note_ok, severity_ok]
    return Result(
        model_id=model_id,
        score=sum(checks_list),
        findings=len(findings),
        latency_s=latency,
        tokens=int(getattr(model, "total_tokens", 0)),
        checks="".join("Y" if value else "-" for value in checks_list),
    )


async def compare(
    model_ids: list[str], key: str, factory: Callable[[str, str], Model] | None = None
) -> list[Result]:
    detail = load_fixture()
    make_model = factory or (lambda model_id, api_key: OpenAIModel(api_key, model_id))
    results = []
    for model_id in model_ids:
        results.append(await evaluate(model_id, make_model(model_id, key), detail))
    return results


def print_results(results: list[Result]) -> None:
    print("MODEL  SCORE  FOUND  LATENCY  TOKENS  CHECKS(R,E,6,N,I,S)")
    for item in results:
        print(
            f"{item.model_id}  {item.score}/6  {item.findings}/6  "
            f"{item.latency_s:.2f}s  {item.tokens}  {item.checks}"
        )
    best = min(results, key=lambda item: (-item.score, item.latency_s, item.tokens, item.model_id))
    print(f"BEST: {best.model_id}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_ids", nargs="+", help="Vultr inference model IDs")
    args = parser.parse_args(argv)
    key = os.environ.get("VULTR_INFERENCE_KEY")
    if not key:
        print("VULTR_INFERENCE_KEY is missing", file=sys.stderr)
        return 2
    results = asyncio.run(compare(args.model_ids, key))
    print_results(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
