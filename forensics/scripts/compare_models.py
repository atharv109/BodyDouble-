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
    matched: int
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
    # Rank every actual/expected pair, then greedily take the strongest
    # non-conflicting assignments. Evidence identity is authoritative; path
    # overlap is the fallback for fixtures whose evidence IDs were renumbered.
    candidates: list[tuple[tuple[int, int, int], str, int, Finding]] = []
    for actual_index, finding in enumerate(actual):
        actual_ids = set(finding.evidence_ids)
        actual_paths = {paths[ref] for ref in actual_ids if ref in paths}
        for expected_item in expected:
            expected_ids = set(expected_item.evidence_ids)
            expected_paths = {paths[ref] for ref in expected_ids if ref in paths}
            id_overlap = len(actual_ids & expected_ids)
            path_overlap = len(actual_paths & expected_paths)
            if not id_overlap and not path_overlap:
                continue
            title_equal = int(normalized(finding.title) == normalized(expected_item.title))
            candidates.append(
                ((id_overlap, path_overlap, title_equal), expected_item.id, actual_index, finding)
            )

    matched: dict[str, Finding] = {}
    used_actual: set[int] = set()
    for _score, expected_id, actual_index, finding in sorted(
        candidates, key=lambda item: (item[0], item[1], -item[2]), reverse=True
    ):
        if expected_id in matched or actual_index in used_actual:
            continue
        matched[expected_id] = finding
        used_actual.add(actual_index)
    return matched


class RecordingModel:
    def __init__(self, delegate: Model) -> None:
        self.delegate = delegate
        self.responses: list[str] = []

    @property
    def total_tokens(self) -> int:
        return int(getattr(self.delegate, "total_tokens", 0))

    async def chat(self, messages: list[dict[str, str]]) -> str:
        response = await self.delegate.chat(messages)
        self.responses.append(response)
        return response


async def evaluate(
    model_id: str, model: Model, detail: CaseDetail, dump_dir: Path | None = None
) -> Result:
    recording = RecordingModel(model)
    started = time.perf_counter()
    findings, timeline = await analyze(recording, detail.case.id, detail.evidence)
    solver_report = await report(recording, detail.evidence, timeline)
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
    if dump_dir is not None:
        dump_dir.mkdir(parents=True, exist_ok=True)
        safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", model_id).strip("._") or "model"

        def raw_json(index: int) -> object:
            if index >= len(recording.responses):
                return None
            try:
                return json.loads(recording.responses[index])
            except json.JSONDecodeError:
                return recording.responses[index]

        payload = {
            "model_id": model_id,
            "raw_findings": raw_json(0),
            "raw_report": raw_json(1),
            "accepted_findings": [item.model_dump(mode="json") for item in findings],
            "report": solver_report.model_dump(mode="json"),
        }
        (dump_dir / f"{safe_id}.json").write_text(
            json.dumps(payload, indent=2) + "\n", encoding="utf-8"
        )
    return Result(
        model_id=model_id,
        score=sum(checks_list),
        matched=len(matched),
        latency_s=latency,
        tokens=int(getattr(model, "total_tokens", 0)),
        checks="".join("Y" if value else "-" for value in checks_list),
    )


async def compare(
    model_ids: list[str],
    key: str,
    factory: Callable[[str, str], Model] | None = None,
    dump_dir: Path | None = None,
) -> list[Result]:
    detail = load_fixture()
    make_model = factory or (lambda model_id, api_key: OpenAIModel(api_key, model_id))
    results = []
    for model_id in model_ids:
        results.append(await evaluate(model_id, make_model(model_id, key), detail, dump_dir))
    return results


def print_results(results: list[Result]) -> None:
    print("MODEL  SCORE  FOUND  LATENCY  TOKENS  CHECKS(R,E,6,N,I,S)")
    for item in results:
        print(
            f"{item.model_id}  {item.score}/6  {item.matched}/6  "
            f"{item.latency_s:.2f}s  {item.tokens}  {item.checks}"
        )
    best = min(results, key=lambda item: (-item.score, item.latency_s, item.tokens, item.model_id))
    print(f"BEST: {best.model_id}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_ids", nargs="+", help="Vultr inference model IDs")
    parser.add_argument("--dump", type=Path, metavar="DIR", help="write raw model JSON per model")
    args = parser.parse_args(argv)
    key = os.environ.get("VULTR_INFERENCE_KEY")
    if not key:
        print("VULTR_INFERENCE_KEY is missing", file=sys.stderr)
        return 2
    results = asyncio.run(compare(args.model_ids, key, dump_dir=args.dump))
    print_results(results)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
