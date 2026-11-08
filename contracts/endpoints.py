"""Control-plane HTTP API (PRD: "HTTP API (control plane)").

The first nine rows are the PRD table. The /twin/jobs rows are the twin's pull
channel: the twin long-polls the control plane over the VPC, so the twin's
firewall group needs no inbound rule at all and the ISO's egress allowlist is
just the case VPC subnet.
"""
from __future__ import annotations

from typing import NamedTuple

from . import models as m


class Endpoint(NamedTuple):
    method: str
    path: str
    request: type | None
    response: type | str | None
    purpose: str
    auth: str  # "human" (operator session), "twin" (X-Twin-Session), "token" (one-time)


ENDPOINTS: list[Endpoint] = [
    Endpoint("GET", "/instances", None, list[m.VultrInstance], "List the account's servers", "human"),
    Endpoint("POST", "/cases", m.OpenCaseRequest, m.Case, "Open a case {instance_id, reason}", "human"),
    Endpoint("GET", "/cases/{id}", None, m.CaseDetail, "Case, steps, findings, actions", "human"),
    Endpoint("GET", "/cases/{id}/stream", None, "text/event-stream", "SSE live feed (contracts.events)", "human"),
    Endpoint("POST", "/cases/{id}/actions/{action_id}/approve", m.ApproveRequest, m.Action,
             "Human approval; applies the action", "human"),
    Endpoint("POST", "/cases/{id}/close", None, m.CaseDetail, "Teardown and seal", "human"),
    Endpoint("GET", "/cases/{id}/bundle", None, "application/zip", "Evidence bundle zip", "human"),
    Endpoint("POST", "/twin/register", m.TwinRegisterRequest, m.TwinRegisterResponse,
             "Forensics ISO checks in (VPC only, one-time token)", "token"),
    # twin pull channel (VPC only)
    Endpoint("GET", "/twin/jobs/next", None, m.ToolCall,
             "Long-poll for the next ToolCall; 204 when none within 25 s", "twin"),
    Endpoint("POST", "/twin/jobs/{job_id}/result", m.ToolResult, None, "Return a ToolResult", "twin"),
    Endpoint("POST", "/twin/heartbeat", None, None, "Liveness every 10 s (F4)", "twin"),
]
