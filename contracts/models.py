"""Body Double data model (PRD: "Data model, API and events").

Six tables -> six models. The case log is the source of truth. These models are
the wire format for the HTTP API, the SSE stream and the DB rows. Owned by the
orchestrator: workers import, never edit.
"""
from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field


# ---------------------------------------------------------------- enums
class CaseState(str, Enum):
    opened = "opened"
    snapshotting = "snapshotting"
    restoring = "restoring"
    sealed = "sealed"
    investigating = "investigating"
    reported = "reported"
    contained = "contained"
    closed = "closed"
    failed = "failed"  # reachable from any non-terminal state; still tears down the twin


# Legal forward transitions. Any non-terminal state may also go to `failed`.
CASE_TRANSITIONS: dict[CaseState, set[CaseState]] = {
    CaseState.opened: {CaseState.snapshotting},
    CaseState.snapshotting: {CaseState.restoring},
    CaseState.restoring: {CaseState.sealed},
    CaseState.sealed: {CaseState.investigating},
    CaseState.investigating: {CaseState.reported},
    CaseState.reported: {CaseState.contained, CaseState.closed},
    CaseState.contained: {CaseState.closed},
    CaseState.closed: set(),
    CaseState.failed: set(),
}


def can_transition(src: CaseState, dst: CaseState) -> bool:
    if dst is CaseState.failed:
        return src not in (CaseState.closed, CaseState.failed)
    return dst in CASE_TRANSITIONS[src]


class StepKind(str, Enum):
    triage = "triage"
    detonate = "detonate"


class Severity(str, Enum):
    critical = "critical"
    high = "high"
    medium = "medium"
    info = "info"


SEVERITY_ORDER = {Severity.critical: 0, Severity.high: 1, Severity.medium: 2, Severity.info: 3}


class ActionKind(str, Enum):
    quarantine_firewall = "quarantine_firewall"  # PATCH /v2/instances/{id} firewall_group_id
    revoke_ssh_key = "revoke_ssh_key"  # shown as a command for the human; no API call
    stop_instance = "stop_instance"  # POST /v2/instances/{id}/halt
    rotate_secrets = "rotate_secrets"  # checklist only; no API call


class ActionStatus(str, Enum):
    proposed = "proposed"
    approved = "approved"
    applied = "applied"
    rejected = "rejected"


class Actor(str, Enum):
    system = "system"
    agent = "agent"
    human = "human"


class ToolName(str, Enum):
    """The planner's only choices (PRD: "Tool list")."""

    os_facts = "os_facts"
    persistence_scan = "persistence_scan"
    auth_scan = "auth_scan"
    recent_files = "recent_files"
    binary_integrity = "binary_integrity"
    listener_config = "listener_config"
    extract = "extract"
    detonate = "detonate"
    custom_script = "custom_script"


# ---------------------------------------------------------------- tables
class Case(BaseModel):
    id: str
    instance_id: str
    instance_label: str
    reason: str
    state: CaseState = CaseState.opened
    snapshot_id: str | None = None
    twin_instance_id: str | None = None
    vpc_id: str | None = None
    firewall_group_id: str | None = None  # the twin's inbound-deny group
    created_at: datetime
    closed_at: datetime | None = None


class Step(BaseModel):
    id: str
    case_id: str
    seq: int
    kind: StepKind
    tool: ToolName
    args: dict[str, Any] = Field(default_factory=dict)
    rationale: str
    code: str  # the script actually run on the twin
    stdout: str = ""
    stderr: str = ""
    exit_code: int | None = None  # None while running
    duration_ms: int | None = None


class Evidence(BaseModel):
    id: str
    case_id: str
    step_id: str | None = None
    path: str  # path on the cloned disk, or "snapshot:<id>" / "dns:<name>"
    sha256: str
    excerpt: str  # truncated, quoted text; never instructions
    injection_flag: bool = False


class Finding(BaseModel):
    id: str
    case_id: str
    title: str
    severity: Severity
    mitre_id: str | None = None
    summary: str
    evidence_ids: list[str] = Field(min_length=1)  # F8: at least one, must exist in case


class Action(BaseModel):
    id: str
    case_id: str
    kind: ActionKind
    target: str  # instance id
    api_method: Literal["GET", "POST", "PATCH", "DELETE"] | None = None
    api_path: str | None = None  # concrete, e.g. "/v2/instances/abc"; None for no-API kinds
    api_body: dict[str, Any] | None = None
    description: str  # human text; for revoke_ssh_key the command to run
    status: ActionStatus = ActionStatus.proposed
    approved_by: str | None = None
    response: dict[str, Any] | None = None  # ApiResponse.model_dump()


class LogEntry(BaseModel):
    seq: int
    case_id: str
    ts: datetime
    actor: Actor
    event: str
    payload: dict[str, Any] = Field(default_factory=dict)
    prev_hash: str  # GENESIS_HASH for seq 0
    hash: str  # see contracts.hashing.entry_hash


GENESIS_HASH = "0" * 64


# ---------------------------------------------------------------- Vultr-facing
class VultrInstance(BaseModel):
    id: str
    label: str
    region: str
    main_ip: str
    internal_ip: str = ""
    status: str  # "pending" | "active"
    power_status: str = "running"
    server_status: str = "ok"
    plan: str = ""
    os: str = ""
    firewall_group_id: str = ""
    vpc_ids: list[str] = Field(default_factory=list)


class VultrSnapshot(BaseModel):
    id: str
    description: str
    status: str  # "pending" | "complete"
    size: int = 0
    date_created: str = ""


class VultrVPC(BaseModel):
    id: str
    region: str
    description: str
    v4_subnet: str
    v4_subnet_mask: int


class VultrFirewallGroup(BaseModel):
    id: str
    description: str


class FirewallRule(BaseModel):
    ip_type: Literal["v4", "v6"] = "v4"
    protocol: Literal["tcp", "udp", "icmp", "gre"] = "tcp"
    subnet: str
    subnet_size: int
    port: str = ""
    notes: str = ""


class CreateTwinRequest(BaseModel):
    """Body for POST /v2/instances. Vultr may reject snapshot_id+iso_id together
    (day-one test T1); the backend then creates from snapshot and calls attach_iso."""

    region: str
    plan: str
    label: str
    snapshot_id: str
    iso_id: str | None = None
    attach_vpc: list[str] = Field(default_factory=list)
    firewall_group_id: str
    enable_ipv6: bool = False
    # base64 JSON {"case_id", "token", "control_plane"}: the one-time registration token for the
    # forensics ISO, read at boot from the metadata service (http://169.254.169.254/v1/user-data).
    user_data: str | None = None


class ApiResponse(BaseModel):
    """Every mutating Vultr call to production is logged as one of these (F10)."""

    method: str
    path: str
    body: dict[str, Any] | None = None
    status_code: int
    response: Any = None


# ---------------------------------------------------------------- seal / blast radius
class SealStatus(BaseModel):
    disk_read_only: bool
    egress_blocked: bool
    detail: dict[str, str] = Field(default_factory=dict)  # raw command output per check

    @property
    def sealed(self) -> bool:
        return self.disk_read_only and self.egress_blocked


class BlastRadius(BaseModel):
    """F16 / close screen. All should be 0."""

    prod_writes_before_approval: int
    packets_out: int
    containers_left: int


# ---------------------------------------------------------------- HTTP bodies
class OpenCaseRequest(BaseModel):
    instance_id: str
    reason: str = Field(min_length=1, max_length=500)


class ApproveRequest(BaseModel):
    """POST /cases/{id}/actions/{action_id}/approve. Requires a human session."""

    approved_by: str


class CaseDetail(BaseModel):
    """GET /cases/{id}"""

    case: Case
    steps: list[Step]
    evidence: list[Evidence]
    findings: list[Finding]
    actions: list[Action]
    seal: SealStatus | None = None
    blast_radius: BlastRadius | None = None


# ---------------------------------------------------------------- twin <-> control plane
class TwinRegisterRequest(BaseModel):
    """POST /twin/register: the forensics ISO checks in over the VPC (F4)."""

    case_id: str
    token: str  # one-time registration token for this case
    vpc_ip: str
    seal: SealStatus


class TwinRegisterResponse(BaseModel):
    session_key: str  # sent as header X-Twin-Session on every later /twin/* call


class Artifact(BaseModel):
    path: str
    sha256: str
    excerpt: str = ""


class ToolCall(BaseModel):
    """One job the twin agent runs against the read-only mount."""

    job_id: str
    case_id: str
    tool: ToolName
    args: dict[str, Any] = Field(default_factory=dict)


class ToolResult(BaseModel):
    job_id: str
    code: str  # exact script executed
    stdout: str
    stderr: str
    exit_code: int
    duration_ms: int
    artifacts: list[Artifact] = Field(default_factory=list)  # files hashed during the run
    dns_queries: list[str] = Field(default_factory=list)  # detonate only
    file_writes: list[str] = Field(default_factory=list)  # detonate only
    # F16, detonate/custom_script: after cleanup; backend sums them into BlastRadius. Must be 0.
    containers_left: int = 0
    packets_out: int = 0  # outbound packets that left the twin
