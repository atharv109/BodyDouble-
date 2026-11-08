"""SSE events on GET /cases/{id}/stream (PRD: "Events on the stream").

Wire format, one event per message:

    event: <EventName>
    id: <case log seq>
    data: <payload JSON>

`id` is the case-log seq that produced the event, so a client can resume with
Last-Event-ID. On connect the server first replays the case so far, then streams live.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel

from .models import (
    Action,
    ApiResponse,
    BlastRadius,
    CaseState,
    Finding,
    Step,
)


class EventName(str, Enum):
    state_changed = "state_changed"
    seal_check = "seal_check"
    step_started = "step_started"
    step_finished = "step_finished"
    dns_captured = "dns_captured"
    finding_added = "finding_added"
    action_proposed = "action_proposed"
    action_applied = "action_applied"
    teardown_done = "teardown_done"


class StateChanged(BaseModel):
    case_id: str
    from_state: CaseState | None
    to_state: CaseState
    detail: str = ""  # e.g. "snapshot 9f.. complete", failure reason


class SealCheck(BaseModel):
    case_id: str
    check: str  # "disk_read_only" | "egress_blocked"
    passed: bool
    output: str  # raw command output shown on screen


class StepStarted(BaseModel):
    step: Step  # exit_code/stdout empty


class StepFinished(BaseModel):
    step: Step  # complete


class DnsCaptured(BaseModel):
    case_id: str
    step_id: str
    query: str  # the domain the detonated file tried to resolve
    answered_with: str  # sinkhole address
    evidence_id: str


class FindingAdded(BaseModel):
    finding: Finding


class ActionProposed(BaseModel):
    action: Action


class ActionApplied(BaseModel):
    action: Action  # status applied (or rejected)
    api: ApiResponse | None  # None for no-API kinds


class TeardownDone(BaseModel):
    case_id: str
    twin_instance_id: str
    twin_status_code: int  # 404 expected (F11)
    vpc_deleted: bool
    blast_radius: BlastRadius


PAYLOADS: dict[EventName, type[BaseModel]] = {
    EventName.state_changed: StateChanged,
    EventName.seal_check: SealCheck,
    EventName.step_started: StepStarted,
    EventName.step_finished: StepFinished,
    EventName.dns_captured: DnsCaptured,
    EventName.finding_added: FindingAdded,
    EventName.action_proposed: ActionProposed,
    EventName.action_applied: ActionApplied,
    EventName.teardown_done: TeardownDone,
}


def format_sse(name: EventName, seq: int, payload: BaseModel) -> str:
    assert isinstance(payload, PAYLOADS[name]), f"{name} needs {PAYLOADS[name].__name__}"
    return f"event: {name.value}\nid: {seq}\ndata: {payload.model_dump_json()}\n\n"


def parse_sse(text: str) -> list[tuple[EventName, int, BaseModel]]:
    """Parse an SSE stream into validated (name, seq, payload) tuples."""
    out = []
    for block in text.strip().split("\n\n"):
        fields = dict(line.split(": ", 1) for line in block.strip().splitlines())
        name = EventName(fields["event"])
        out.append((name, int(fields["id"]), PAYLOADS[name].model_validate_json(fields["data"])))
    return out
