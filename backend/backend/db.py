"""SQLAlchemy ORM for the six PRD tables plus control-plane-only tables
(jobs, reports, warm twins). Postgres in production via DATABASE_URL,
SQLite in tests — same models, same code.

Timestamps are stored as naive UTC (SQLAlchemy's SQLite DATETIME drops tzinfo,
so we normalize at the edge and compare consistently).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import JSON, DateTime, String, Text, create_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from contracts.agent import Report, TimelineEntry
from contracts.models import (
    Action,
    ActionKind,
    ActionStatus,
    Actor,
    Case,
    CaseState,
    Evidence,
    Finding,
    LogEntry,
    Severity,
    Step,
    StepKind,
    ToolName,
    ToolResult,
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class CaseRow(Base):
    __tablename__ = "cases"
    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(64))
    instance_label: Mapped[str] = mapped_column(String(128))
    reason: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(16), default=CaseState.opened.value)
    snapshot_id: Mapped[str | None] = mapped_column(String(64))
    twin_instance_id: Mapped[str | None] = mapped_column(String(64))
    vpc_id: Mapped[str | None] = mapped_column(String(64))
    firewall_group_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime)
    # control-plane-only columns (never on the wire)
    operator: Mapped[str] = mapped_column(String(64), default="operator")
    reg_token: Mapped[str | None] = mapped_column(String(128))
    twin_internal_ip: Mapped[str | None] = mapped_column(String(64))
    vpc_subnet: Mapped[str | None] = mapped_column(String(64))
    vpc_mask: Mapped[int | None] = mapped_column()
    quarantine_group_id: Mapped[str | None] = mapped_column(String(64))
    seal: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    blast_radius: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    def to_model(self) -> Case:
        return Case(
            id=self.id, instance_id=self.instance_id, instance_label=self.instance_label,
            reason=self.reason, state=CaseState(self.state), snapshot_id=self.snapshot_id,
            twin_instance_id=self.twin_instance_id, vpc_id=self.vpc_id,
            firewall_group_id=self.firewall_group_id, created_at=self.created_at,
            closed_at=self.closed_at,
        )


class StepRow(Base):
    __tablename__ = "steps"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(32))
    seq: Mapped[int]
    kind: Mapped[str] = mapped_column(String(16))
    tool: Mapped[str] = mapped_column(String(32))
    args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    rationale: Mapped[str] = mapped_column(Text)
    code: Mapped[str] = mapped_column(Text)
    stdout: Mapped[str] = mapped_column(Text, default="")
    stderr: Mapped[str] = mapped_column(Text, default="")
    exit_code: Mapped[int | None]
    duration_ms: Mapped[int | None]

    def to_model(self) -> Step:
        return Step(
            id=self.id, case_id=self.case_id, seq=self.seq, kind=StepKind(self.kind),
            tool=ToolName(self.tool), args=self.args or {}, rationale=self.rationale,
            code=self.code, stdout=self.stdout or "", stderr=self.stderr or "",
            exit_code=self.exit_code, duration_ms=self.duration_ms,
        )

    def apply_result(self, result: ToolResult) -> None:
        self.code = result.code
        self.stdout = result.stdout
        self.stderr = result.stderr
        self.exit_code = result.exit_code
        self.duration_ms = result.duration_ms


class EvidenceRow(Base):
    __tablename__ = "evidence"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(32))
    step_id: Mapped[str | None] = mapped_column(String(64))
    path: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(String(64))
    excerpt: Mapped[str] = mapped_column(Text, default="")
    injection_flag: Mapped[bool] = mapped_column(default=False)

    def to_model(self) -> Evidence:
        return Evidence(
            id=self.id, case_id=self.case_id, step_id=self.step_id, path=self.path,
            sha256=self.sha256, excerpt=self.excerpt, injection_flag=self.injection_flag,
        )


class FindingRow(Base):
    __tablename__ = "findings"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(Text)
    severity: Mapped[str] = mapped_column(String(16))
    mitre_id: Mapped[str | None] = mapped_column(String(32))
    summary: Mapped[str] = mapped_column(Text)
    evidence_ids: Mapped[list[str]] = mapped_column(JSON, default=list)

    def to_model(self) -> Finding:
        return Finding(
            id=self.id, case_id=self.case_id, title=self.title,
            severity=Severity(self.severity), mitre_id=self.mitre_id, summary=self.summary,
            evidence_ids=self.evidence_ids or [],
        )


class ActionRow(Base):
    __tablename__ = "actions"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(32))
    target: Mapped[str] = mapped_column(String(64))
    api_method: Mapped[str | None] = mapped_column(String(8))
    api_path: Mapped[str | None] = mapped_column(String(255))
    api_body: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    description: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(16), default=ActionStatus.proposed.value)
    approved_by: Mapped[str | None] = mapped_column(String(64))
    response: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    def to_model(self) -> Action:
        return Action(
            id=self.id, case_id=self.case_id, kind=ActionKind(self.kind), target=self.target,
            api_method=self.api_method, api_path=self.api_path, api_body=self.api_body,
            description=self.description, status=ActionStatus(self.status),
            approved_by=self.approved_by, response=self.response,
        )


class LogEntryRow(Base):
    __tablename__ = "log"
    seq: Mapped[int] = mapped_column(primary_key=True)
    case_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime)
    actor: Mapped[str] = mapped_column(String(8))
    event: Mapped[str] = mapped_column(String(32))
    payload: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))

    def to_model(self) -> LogEntry:
        return LogEntry(
            seq=self.seq, case_id=self.case_id, ts=self.ts, actor=Actor(self.actor),
            event=self.event, payload=self.payload or {}, prev_hash=self.prev_hash, hash=self.hash,
        )


class JobRow(Base):
    """One ToolCall queued to the twin, with the ToolResult when it returns."""
    __tablename__ = "jobs"
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    case_id: Mapped[str] = mapped_column(String(32))
    tool: Mapped[str] = mapped_column(String(32))
    args: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    enqueued_at: Mapped[datetime] = mapped_column(DateTime)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSON)

    def to_result(self) -> ToolResult | None:
        return ToolResult.model_validate(self.result) if self.result else None


class ReportRow(Base):
    __tablename__ = "reports"
    case_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    summary: Mapped[str] = mapped_column(Text)
    timeline: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)
    ranked_actions: Mapped[list[str]] = mapped_column(JSON, default=list)
    rogue_ssh_keys: Mapped[list[str]] = mapped_column(JSON, default=list)
    secrets_found: Mapped[list[str]] = mapped_column(JSON, default=list)

    def to_model(self) -> Report:
        return Report(
            summary=self.summary,
            timeline=[TimelineEntry.model_validate(t) for t in self.timeline or []],
            ranked_actions=[ActionKind(a) for a in self.ranked_actions or []],
            rogue_ssh_keys=self.rogue_ssh_keys or [],
            secrets_found=self.secrets_found or [],
        )


class WarmTwinRow(Base):
    """F17: a pre-snapshotted, pre-restored twin waiting to be adopted by a case."""
    __tablename__ = "warm_twins"
    id: Mapped[int] = mapped_column(primary_key=True)
    instance_id: Mapped[str] = mapped_column(String(64))
    instance_label: Mapped[str] = mapped_column(String(128))
    snapshot_id: Mapped[str] = mapped_column(String(64))
    twin_instance_id: Mapped[str] = mapped_column(String(64))
    vpc_id: Mapped[str] = mapped_column(String(64))
    firewall_group_id: Mapped[str] = mapped_column(String(64))
    twin_internal_ip: Mapped[str | None] = mapped_column(String(64))
    vpc_subnet: Mapped[str | None] = mapped_column(String(64))
    vpc_mask: Mapped[int | None] = mapped_column()
    iso_id: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime)
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime)


def make_engine(database_url: str):
    return create_engine(database_url, future=True)


def init_db(engine) -> None:
    Base.metadata.create_all(engine)
