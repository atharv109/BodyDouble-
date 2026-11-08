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
    # sensors and alerts (plug and play). auth "sensor" = X-BD-Signature with the instance token,
    # "webhook" = X-BD-Signature with BD_WEBHOOK_SECRET, "public" = none, "dev" = fake mode only.
    Endpoint("POST", "/sensors", m.SensorEnrollRequest, m.SensorEnrollResponse,
             "Enroll a server: per-instance token + install command, shown once", "human"),
    Endpoint("GET", "/sensors", None, list[m.SensorStatus], "Watched servers and their health", "human"),
    Endpoint("GET", "/sensors/install.sh", None, "text/x-shellscript",
             "Serves forensics' sensor/install.sh verbatim; args: url instance_id token", "public"),
    Endpoint("POST", "/sensors/report", m.SensorReport, m.Alert, "Sensor alert -> auto case", "sensor"),
    Endpoint("POST", "/sensors/heartbeat", m.SensorHeartbeat, None, "Sensor liveness", "sensor"),
    Endpoint("POST", "/alerts/webhook", m.WebhookAlert, m.Alert, "Wazuh/Falco/other -> auto case", "webhook"),
    Endpoint("GET", "/alerts", None, list[m.Alert], "Alert inbox, newest first", "human"),
    # choose the fix
    Endpoint("POST", "/cases/{id}/actions", m.CustomActionRequest, m.Action,
             "Operator's own fix (menu kind or manual_plan); still needs approve", "human"),
    # interactive demo
    Endpoint("POST", "/dev/infect", m.InfectRequest, m.InfectResponse,
             "Plant chosen attacks on a fake server; its sensor fires; case auto-opens", "dev"),
]
