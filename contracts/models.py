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
    manual_plan = "manual_plan"  # the human's own written plan; recorded, never executed, no API call


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
    alert_id: str | None = None  # set when a sensor/webhook alert opened this case
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
    recommended: bool = False  # exactly one agent-proposed action per case is the recommended fix
    created_by: Actor = Actor.agent  # Actor.human for CustomActionRequest
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
    """Body for POST /v2/instances. Preferred: snapshot_id + iso_id in one call (T1).
    If Vultr rejects that, the T1 fallback (PRD) is: create with iso_id only, then
    VultrClient.restore_snapshot() onto it with the ISO still attached, so the cloned
    OS never boots. Attaching the ISO after a snapshot-only create is the last resort."""

    region: str
    plan: str
    label: str
    snapshot_id: str | None = None
    iso_id: str | None = None
    attach_vpc: list[str] = Field(default_factory=list)
    firewall_group_id: str
    enable_ipv6: bool = False
    # base64 JSON {"case_id", "token", "control_plane", "vpc_subnet", "vpc_ip"}: the forensics ISO's
    # ONLY deploy-time input, read at boot from the metadata service
    # (http://169.254.169.254/v1/user-data). The ISO validates every value strictly and fails closed;
    # it never reads config from any block device (the cloned disk is attacker-controlled).
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


# ---------------------------------------------------------------- sensors and alerts (plug and play)
# Trust rule: a sensor runs on a server the attacker may control, so every alert is untrusted DATA.
# An alert may only START a case (snapshot + sealed twin + report, all read-only for production).
# It never approves, applies or proposes containment, and its text never reaches the agent as
# instructions (it becomes Case.reason, shown quoted). The sensor is push-only: it opens no port,
# accepts no commands and ignores response bodies.
class SensorSignal(str, Enum):
    file_changed = "file_changed"  # cron, authorized_keys, system binaries changed vs baseline
    new_outbound = "new_outbound"  # outbound destination not in the baseline
    heartbeat_lost = "heartbeat_lost"  # raised by the control plane: no heartbeat for HEARTBEAT_LOST_S
    external = "external"  # Wazuh / Falco / any webhook


HEARTBEAT_EVERY_S = 60
HEARTBEAT_LOST_S = 180
SENSOR_CLOCK_SKEW_S = 300  # reject reports whose sent_at is further than this from now
ALERTS_PER_INSTANCE_PER_MIN = 10  # over this: 429, no alert, no case


class Alert(BaseModel):
    id: str
    instance_id: str
    signal: SensorSignal
    source: Literal["sensor", "control_plane", "wazuh", "falco", "webhook"]
    summary: str = Field(max_length=500)
    detail: dict[str, str] = Field(default_factory=dict)  # untrusted; rendered as text only
    received_at: datetime
    # One live case per instance: if a non-terminal case exists, the alert attaches to it.
    case_id: str | None = None


class SensorEnrollRequest(BaseModel):
    """POST /sensors (human). Issues a per-instance token, shown once."""

    instance_id: str


class SensorEnrollResponse(BaseModel):
    instance_id: str
    token: str  # 32 random bytes, hex; stored hashed; re-enrolling rotates it
    # curl -fsSL <BD_PUBLIC_URL>/api/sensors/install.sh | sudo sh -s -- <BD_PUBLIC_URL> <instance_id> <token>
    install_command: str
    startup_script: str  # the same install as a Vultr startup script ("#!/bin/sh" ...) for new servers


class SensorStatus(BaseModel):
    """GET /sensors (human): one row per enrolled instance."""

    instance_id: str
    enrolled_at: datetime
    last_seen: datetime | None = None
    healthy: bool  # last_seen within HEARTBEAT_LOST_S


class SensorReport(BaseModel):
    """POST /sensors/report. Header X-BD-Signature = hashing.sensor_signature(token, raw body)."""

    instance_id: str
    signal: Literal[SensorSignal.file_changed, SensorSignal.new_outbound]
    summary: str = Field(min_length=1, max_length=500)
    detail: dict[str, str] = Field(default_factory=dict, max_length=20)
    sent_at: datetime
    nonce: str = Field(pattern=r"^[A-Za-z0-9]{16,64}$")  # unique per instance; replay -> 409


class SensorHeartbeat(BaseModel):
    """POST /sensors/heartbeat, signed like SensorReport."""

    instance_id: str
    sent_at: datetime
    nonce: str = Field(pattern=r"^[A-Za-z0-9]{16,64}$")


class WebhookAlert(BaseModel):
    """POST /alerts/webhook. Header X-BD-Signature = sensor_signature(BD_WEBHOOK_SECRET, raw body).
    Disabled (404) when BD_WEBHOOK_SECRET is unset."""

    instance_id: str
    source: Literal["wazuh", "falco", "webhook"] = "webhook"
    summary: str = Field(min_length=1, max_length=500)
    detail: dict[str, str] = Field(default_factory=dict, max_length=20)


class CustomActionRequest(BaseModel):
    """POST /cases/{id}/actions (human, case in `reported`): the operator's own fix.
    kind is a menu kind or manual_plan. The backend builds any API call itself with the same builder
    as agent proposals, never from client-supplied paths or bodies. It still needs Approve."""

    kind: ActionKind
    description: str = Field(min_length=1, max_length=2000)
    created_by: str = Field(min_length=1, max_length=80)


# ---------------------------------------------------------------- interactive demo (fake mode only)
class Attack(str, Enum):
    cron_backdoor = "cron_backdoor"
    rogue_ssh_key = "rogue_ssh_key"
    replaced_top = "replaced_top"
    c2_beacon = "c2_beacon"  # the payload + its miner drop
    ai_note = "ai_note"  # text on the disk addressed to an AI investigator (F13)


# Which recorded fixture findings each planted attack produces. A demo case replays only the
# steps/evidence/findings of the chosen attacks; none chosen = clean-control result (F15, 0 findings).
ATTACK_FINDINGS: dict[Attack, list[str]] = {
    Attack.cron_backdoor: ["fd-01"],
    Attack.rogue_ssh_key: ["fd-02"],
    Attack.replaced_top: ["fd-03"],
    Attack.c2_beacon: ["fd-04", "fd-05"],
    Attack.ai_note: ["fd-06"],
}
# act-1 quarantine (recommended), act-3 stop, act-4 rotate: proposed whenever any finding exists.
# act-2 revoke key: only with rogue_ssh_key.
ATTACK_ACTIONS: dict[Attack, list[str]] = {Attack.rogue_ssh_key: ["act-2"]}
ALWAYS_ACTIONS = ["act-1", "act-3", "act-4"]


class InfectRequest(BaseModel):
    """POST /dev/infect (fake mode only; 404 in real mode). Plants the chosen attacks on a fresh
    fake server, fires the matching sensor alert, and auto-opens its case (stops at `reported`)."""

    attacks: list[Attack] = Field(default_factory=list, max_length=5)


class InfectResponse(BaseModel):
    instance_id: str
    alert_id: str | None  # None when no attacks chosen: no alert, case opened as a clean control
    case_id: str
