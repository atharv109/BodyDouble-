"""FastAPI control plane. All routes are thin: they pull AppState from
request.app.state.bd and delegate to CaseService / TwinChannel.

Auth (per contracts.endpoints `auth` column):
  * human endpoints require an operator session — POST /auth/session mints one
    (cookie bd_session, also accepted as X-Human-Session header);
  * /twin/* uses the one-time registration token then X-Twin-Session, and only
    accepts requests from the case's VPC subnet.

Endpoint shapes are owned here (TASK.md); every change is logged to
~/bd-bridge/to-frontend.md.
"""
from __future__ import annotations

import asyncio
import json
import hashlib
import hmac
import ipaddress
import logging
import secrets
from datetime import timedelta, timezone
from pathlib import Path

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from contracts.models import (
    Action,
    ApproveRequest,
    Case,
    CaseDetail,
    CustomActionRequest,
    OpenCaseRequest,
    SensorEnrollRequest,
    SensorEnrollResponse,
    SensorStatus,
    ToolName,
    ToolCall,
    Actor,
    Step,
    StepKind,
    CaseState,
    SensorReport,
    SensorHeartbeat,
    Alert,
    SensorSignal,
    WebhookAlert,
    Attack,
    ATTACK_FINDINGS,
    InfectRequest,
    InfectResponse,
    VultrInstance,
    SENSOR_CLOCK_SKEW_S,
    ToolCall,
    ToolResult,
    TwinRegisterRequest,
    TwinRegisterResponse,
)
from contracts.vultr import FakeVultr, VultrError, VultrNotFound
from contracts.hashing import sensor_signature
from contracts.events import StepFinished, StepStarted
from .db import StepRow

from .sessions import mint, verify
from .db import AlertRow, CaseRow, SensorNonceRow, SensorRow, utcnow
from .state import AppState, build_state
from .service import ActionConflict, AlertRateLimit, TransitionError
from .twin import TwinChannelError, in_subnet

COOKIE_NAME = "bd_session"
log = logging.getLogger("backend")


class AnalystRunRequest(BaseModel):
    tool: ToolName
    args: dict = Field(default_factory=dict)


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _twin_channel_error(e: TwinChannelError) -> HTTPException:
    return HTTPException(e.status_code, e.detail)


def _reject_case_vpc_source(request: Request) -> None:
    ip = _client_ip(request)
    state = request.app.state.bd
    with state.sf() as session:
        networks = session.execute(
            select(CaseRow.vpc_subnet, CaseRow.vpc_mask)
            .where(CaseRow.vpc_subnet.is_not(None), CaseRow.vpc_mask.is_not(None))
        ).all()
    if any(in_subnet(ip, subnet, mask) for subnet, mask in networks):
        raise HTTPException(403, "human API is not accessible from a case VPC")


async def get_operator(
    request: Request,
    bd_session: str | None = Cookie(default=None),
) -> str | None:
    _reject_case_vpc_source(request)
    token = bd_session or request.headers.get("X-Human-Session")
    if not token:
        return None
    return verify(token, request.app.state.bd.settings.app_secret)


async def require_human(operator: str | None = Depends(get_operator)) -> str:
    if operator is None:
        raise HTTPException(401, "human session required (POST /auth/session)")
    return operator


def create_app(state: AppState | None = None) -> FastAPI:
    if state is None:
        state = build_state()
    app = FastAPI(
        title="Body Double control plane",
        version="0.1.0",
        description="Snapshot a suspect server, investigate a sealed twin, "
                    "propose containment a human approves.",
    )
    app.state.bd = state
    vpc_network = (ipaddress.ip_network(state.settings.investigation_vpc_subnet,
                                        strict=False)
                   if state.settings.investigation_vpc_subnet else None)

    @app.middleware("http")
    async def restrict_investigation_vpc(request: Request, call_next):
        """The investigation VPC can see only the twin pull channel."""
        try:
            from_vpc = (vpc_network is not None
                        and ipaddress.ip_address(_client_ip(request)) in vpc_network)
        except ValueError:
            from_vpc = False
        if from_vpc and not request.url.path.startswith("/twin/"):
            log.warning("blocked non-twin request from investigation VPC: %s %s source=%s",
                        request.method, request.url.path, _client_ip(request))
            return JSONResponse({"detail": "Not Found"}, status_code=404)
        return await call_next(request)

    async def heartbeat_watch_loop():
        while True:
            await asyncio.sleep(30)
            try:
                await state.service.check_heartbeat_losses()
            except asyncio.CancelledError:
                raise
            except Exception:
                # A transient watcher failure must not stop API service; the
                # next scan is idempotent and retries any still-due lapse.
                import logging
                logging.getLogger("backend").exception("heartbeat watcher failed")

    @app.on_event("startup")
    async def start_heartbeat_watcher():
        state.heartbeat_task = asyncio.create_task(heartbeat_watch_loop())

    @app.on_event("shutdown")
    async def stop_heartbeat_watcher():
        if state.heartbeat_task is not None:
            state.heartbeat_task.cancel()
            await asyncio.gather(state.heartbeat_task, return_exceptions=True)
            state.heartbeat_task = None

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": True, "vultr": "fake" if state.is_fake else "real"}

    # ---------------------------------------------------------------- auth
    @app.get("/auth/config")
    async def auth_config():
        return {"password_required": bool(state.settings.vultr_api_key)}

    @app.post("/auth/session")
    async def create_session(body: dict, response: Response, request: Request):
        _reject_case_vpc_source(request)
        operator = (body or {}).get("operator", "").strip()
        if not operator or len(operator) > 64:
            raise HTTPException(422, "operator name required (1-64 chars)")
        password_required = bool(state.settings.vultr_api_key)
        if password_required:
            supplied = (body or {}).get("password")
            expected = state.settings.operator_password
            if not isinstance(supplied, str) or not secrets.compare_digest(
                supplied, expected
            ):
                raise HTTPException(401, "invalid operator credentials")
        token = mint(operator, state.settings.app_secret, state.settings.session_ttl_s)
        response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax")
        return {"operator": operator, "session_token": token,
                "password_required": password_required}

    # ---------------------------------------------------------------- F1
    @app.get("/instances", dependencies=[Depends(require_human)])
    async def list_instances():
        return await state.vultr.list_instances()

    # ------------------------------------------------------------- sensors
    @app.post("/sensors", response_model=SensorEnrollResponse)
    async def enroll_sensor(body: SensorEnrollRequest,
                            _: str = Depends(require_human)):
        try:
            await state.vultr.get_instance(body.instance_id)
        except VultrNotFound:
            raise HTTPException(404, f"unknown instance {body.instance_id}")
        token = secrets.token_hex(32)
        now = utcnow()
        with state.sf() as session:
            row = session.get(SensorRow, body.instance_id)
            if row is None:
                row = SensorRow(instance_id=body.instance_id,
                                token_sha256="", enrolled_at=now)
                session.add(row)
            row.token_sha256 = hashlib.sha256(token.encode()).hexdigest()
            row.enrolled_at = now
            row.last_seen = None
            session.commit()
        state.sensor_tokens[body.instance_id] = token
        url = state.settings.public_url
        command = (f"curl -fsSL {url}/api/sensors/install.sh | sudo sh -s -- "
                   f"{url} {body.instance_id} {token}")
        return SensorEnrollResponse(
            instance_id=body.instance_id, token=token,
            install_command=command,
            startup_script=f"#!/bin/sh\n{command}\n",
        )

    @app.get("/sensors", response_model=list[SensorStatus])
    async def list_sensors(_: str = Depends(require_human)):
        now = state.service.now()
        with state.sf() as session:
            rows = session.execute(select(SensorRow).order_by(SensorRow.instance_id)).scalars()
            return [SensorStatus(
                instance_id=row.instance_id, enrolled_at=row.enrolled_at,
                last_seen=row.last_seen,
                healthy=((row.is_demo and state.is_fake) or
                         (row.last_seen is not None and
                          row.last_seen >= now - timedelta(seconds=180))),
            ) for row in rows]

    @app.get("/sensors/install.sh", include_in_schema=True)
    async def sensor_installer():
        path = Path(__file__).resolve().parents[2] / "sensor" / "install.sh"
        if not path.is_file():
            raise HTTPException(404, "sensor installer is not available")
        return FileResponse(path, media_type="text/x-shellscript")

    async def _authenticated_sensor(request: Request, model_type):
        raw = await request.body()
        try:
            body = model_type.model_validate_json(raw)
        except Exception as e:
            raise HTTPException(422, "invalid sensor payload") from e
        token = state.sensor_tokens.get(body.instance_id)
        signature = request.headers.get("X-BD-Signature")
        if token is None or signature is None or not hmac.compare_digest(
                signature, sensor_signature(token, raw)):
            raise HTTPException(401, "invalid sensor signature")
        sent_at = body.sent_at
        if sent_at.tzinfo is not None:
            sent_at = sent_at.astimezone(timezone.utc).replace(tzinfo=None)
        now = state.service.now()
        if abs((now - sent_at).total_seconds()) > SENSOR_CLOCK_SKEW_S:
            raise HTTPException(401, "sensor timestamp outside allowed skew")
        with state.sf() as session:
            session.add(SensorNonceRow(instance_id=body.instance_id,
                                       nonce=body.nonce, received_at=now))
            try:
                session.commit()
            except IntegrityError:
                session.rollback()
                raise HTTPException(409, "sensor nonce already used")
        return body, now

    @app.post("/sensors/report", response_model=Alert)
    async def sensor_report(request: Request):
        body, now = await _authenticated_sensor(request, SensorReport)
        try:
            return await state.service.create_alert(
                body.instance_id, body.signal, "sensor", body.summary, body.detail,
                now=now)
        except AlertRateLimit:
            raise HTTPException(429, "alert rate limit exceeded")

    @app.post("/sensors/heartbeat", status_code=204)
    async def sensor_heartbeat(request: Request):
        body, now = await _authenticated_sensor(request, SensorHeartbeat)
        with state.sf() as session:
            row = session.get(SensorRow, body.instance_id)
            if row is None:
                raise HTTPException(401, "invalid sensor signature")
            row.last_seen = now
            session.commit()
        return Response(status_code=204)

    # ------------------------------------------------------------- alerts
    @app.post("/alerts/webhook", response_model=Alert)
    async def alert_webhook(request: Request):
        secret = state.settings.webhook_secret
        if not secret:
            raise HTTPException(404, "webhook alert intake is disabled")
        raw = await request.body()
        signature = request.headers.get("X-BD-Signature")
        if signature is None or not hmac.compare_digest(
                signature, sensor_signature(secret, raw)):
            raise HTTPException(401, "invalid webhook signature")
        try:
            body = WebhookAlert.model_validate_json(raw)
        except Exception as e:
            raise HTTPException(422, "invalid webhook payload") from e
        try:
            await state.vultr.get_instance(body.instance_id)
        except VultrNotFound:
            raise HTTPException(404, f"unknown instance {body.instance_id}")
        try:
            return await state.service.create_alert(
                body.instance_id, SensorSignal.external, body.source,
                body.summary, body.detail)
        except AlertRateLimit:
            raise HTTPException(429, "alert rate limit exceeded")

    @app.get("/alerts", response_model=list[Alert])
    async def list_alerts(_: str = Depends(require_human)):
        with state.sf() as session:
            rows = session.execute(select(AlertRow).order_by(
                AlertRow.received_at.desc(), AlertRow.id.desc())).scalars()
            return [row.to_model() for row in rows]

    @app.post("/cases", response_model=Case, status_code=201,
              dependencies=[Depends(require_human)])
    async def open_case(body: OpenCaseRequest, operator: str = Depends(require_human)):
        try:
            case = await state.service.open_case(body.instance_id, body.reason, operator=operator)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))
        except VultrError:
            raise HTTPException(502, "Vultr API error while opening the case")
        return await state.service.run_case(case.id)

    @app.post("/dev/fake-case", response_model=Case, status_code=201)
    async def dev_fake_case(body: dict | None = None,
                            _: str = Depends(require_human)):
        if state.settings.vultr_api_key or not state.is_fake:
            raise HTTPException(404, "development fake case is unavailable")
        for task in state.fake_twin_tasks.values():
            task.cancel()
        if state.fake_twin_tasks:
            await asyncio.gather(*state.fake_twin_tasks.values(), return_exceptions=True)
        state.fake_twin_tasks.clear()
        from .db import Base
        from .twin import TwinChannel
        with state.sf() as session:
            for table in reversed(Base.metadata.sorted_tables):
                session.execute(table.delete())
            session.commit()
        state.vultr = FakeVultr()
        state.service.vultr = state.vultr
        state.channel = TwinChannel(state.sf, state.settings)
        state.service.channel = state.channel
        body = body or {}
        instance_id = body.get("instance_id", "inst-shop-prod")
        reason = body.get("reason", "Development demo: investigate shop-prod")
        production = state.vultr.instances.get(instance_id)
        if production is not None:
            production.firewall_group_id = "fw-shop-web"
            production.power_status = "running"
        try:
            case = await state.service.open_case(instance_id, reason, operator="dev-demo")
            return await state.service.run_case(
                case.id, force_full=True, auto_apply=False, auto_close=False
            )
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(422, str(e))

    @app.post("/dev/infect", response_model=InfectResponse, status_code=201)
    async def dev_infect(body: InfectRequest,
                         _: str = Depends(require_human)):
        if state.settings.vultr_api_key or not state.is_fake:
            raise HTTPException(404, "development infection demo is unavailable")
        chosen = set(body.attacks)
        while True:
            suffix = secrets.token_hex(2)
            instance_id = f"inst-demo-{suffix}"
            if instance_id not in state.vultr.instances:
                break
        label = f"demo-{suffix}"
        state.vultr.instances[instance_id] = VultrInstance(
            id=instance_id, label=label, region="ewr",
            main_ip=f"192.0.2.{20 + len(state.vultr.instances)}",
            status="active", plan="vc2-1c-2gb", os="Ubuntu 24.04 LTS x64",
            firewall_group_id="fw-shop-web")
        now = state.service.now()
        token = secrets.token_hex(32)
        with state.sf() as session:
            session.add(SensorRow(
                instance_id=instance_id,
                token_sha256=hashlib.sha256(token.encode()).hexdigest(),
                enrolled_at=now, last_seen=now, is_demo=True))
            session.commit()
        state.sensor_tokens[instance_id] = token
        finding_ids = {
            finding_id for attack in chosen for finding_id in ATTACK_FINDINGS[attack]
        }
        if chosen:
            names = ", ".join(sorted(attack.value for attack in chosen))
            alert = await state.service.create_alert(
                instance_id, SensorSignal.file_changed, "sensor",
                f"Demo sensor detected planted attacks: {names}",
                {"attacks": names}, now=now, rate_limit=False,
                fixture_finding_ids=finding_ids, case_operator="dev-infect")
            case_id = alert.case_id
            alert_id = alert.id
        else:
            case = await state.service.open_case(
                instance_id, "Clean control: no attacks planted",
                operator="dev-infect")
            await state.service.run_case(
                case.id, force_full=True, auto_close=False,
                fixture_finding_ids=set())
            case_id, alert_id = case.id, None
        return InfectResponse(instance_id=instance_id, alert_id=alert_id,
                              case_id=case_id)

    @app.get("/cases/{case_id}", response_model=CaseDetail,
             dependencies=[Depends(require_human)])
    async def get_case(case_id: str):
        try:
            return state.service.detail(case_id)
        except LookupError as e:
            raise HTTPException(404, str(e))

    @app.post("/cases/{case_id}/analyst/run")
    async def analyst_run(case_id: str, body: AnalystRunRequest,
                          operator: str = Depends(require_human)):
        try:
            row = state.service.row(case_id)
        except LookupError as e:
            raise HTTPException(404, str(e))
        if CaseState(row.state) not in (CaseState.sealed, CaseState.investigating,
                                        CaseState.reported, CaseState.contained):
            raise HTTPException(409, "case must be sealed and live")
        tool = body.tool
        args = body.args
        if (not isinstance(args, dict)
                or len(json.dumps(args, separators=(",", ":")).encode()) > 16_384):
            raise HTTPException(422, "args must be an object under 16 KiB")
        from bd_forensics.tools import valid_args
        if not valid_args(tool, args):
            raise HTTPException(422, "invalid or unsafe tool arguments")
        step_id = state.service._next_id(StepRow, case_id, "step")
        call = ToolCall(job_id=f"{case_id}-{step_id}-job", case_id=case_id,
                        tool=tool, args=args)
        step = Step(id=step_id, case_id=case_id, seq=int(step_id.rsplit("-", 1)[1]),
                    kind=StepKind.detonate if tool.value == "detonate" else StepKind.triage,
                    tool=tool, args=args, rationale="human analyst request", code="")
        with state.sf() as session:
            session.add(StepRow.from_model(step))
            session.commit()
        state.log.append(case_id, "step_started", StepStarted(step=step), actor=Actor.human)
        try:
            result = await asyncio.wait_for(state.channel.enqueue(call),
                                            timeout=state.settings.job_timeout_s)
        except asyncio.TimeoutError:
            raise HTTPException(504, "analyst tool timed out")
        if (len(result.stdout.encode()) > 65_536
                or len(result.stderr.encode()) > 16_384):
            raise HTTPException(502, "tool output exceeds limits")
        if (result.duration_ms < 0
                or result.duration_ms > int(state.settings.job_timeout_s * 1000) + 1_000):
            raise HTTPException(502, "tool duration exceeds limit")
        step = step.model_copy(update={"code": result.code, "stdout": result.stdout,
                                       "stderr": result.stderr,
                                       "exit_code": result.exit_code,
                                       "duration_ms": result.duration_ms})
        with state.sf() as session:
            persisted = session.get(StepRow, step.id)
            persisted.code, persisted.stdout, persisted.stderr = step.code, step.stdout, step.stderr
            persisted.exit_code, persisted.duration_ms = step.exit_code, step.duration_ms
            session.commit()
        state.log.append(case_id, "step_finished", StepFinished(step=step), actor=Actor.human)
        state.log.append(case_id, "human_tool_run", {"operator": operator,
                        "step_id": step.id, "tool": tool.value,
                        "exit_code": result.exit_code}, actor=Actor.human)
        if result.exit_code == 126 and result.stderr.startswith("sandbox unavailable"):
            raise HTTPException(503, "sandbox unavailable for sandboxed tool")
        return {"step": step, "result": result}

    @app.get("/cases/{case_id}/stream", dependencies=[Depends(require_human)])
    async def stream_case(case_id: str, request: Request,
                          last_event_id: str | None = Header(default=None)):
        try:
            state.service.row(case_id)
        except LookupError as e:
            raise HTTPException(404, str(e))
        try:
            resume_after = int(last_event_id) if last_event_id is not None else -1
        except ValueError:
            raise HTTPException(400, "Last-Event-ID must be an integer")

        async def frames():
            queue = state.bus.subscribe(case_id)
            try:
                replay, replay_last = state.log.sse_replay(case_id)
                if resume_after < 0:
                    if replay:
                        yield replay
                else:
                    for entry in state.log.entries(case_id):
                        if entry.seq > resume_after and entry.event in state.log_event_names:
                            yield state.log.format_entry(entry)
                    replay_last = max(replay_last, resume_after)
                if state.service.model(case_id).state.value in ("closed", "failed"):
                    return
                while not await request.is_disconnected():
                    try:
                        seq, frame = await asyncio.wait_for(queue.get(), 15)
                    except asyncio.TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    if seq > replay_last and seq > resume_after:
                        yield frame
                    if state.service.model(case_id).state.value in ("closed", "failed"):
                        return
            finally:
                state.bus.unsubscribe(case_id, queue)

        return StreamingResponse(frames(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache"})

    # ---------------------------------------------------------------- F4: twin channel
    @app.post("/twin/register", response_model=TwinRegisterResponse)
    async def twin_register(body: TwinRegisterRequest, request: Request):
        try:
            return state.channel.register(body.case_id, body.token, body.vpc_ip,
                                          body.seal, _client_ip(request))
        except TwinChannelError as e:
            raise _twin_channel_error(e)

    @app.post("/twin/heartbeat", status_code=204)
    async def twin_heartbeat(request: Request,
                             x_twin_session: str | None = Header(default=None)):
        try:
            sess, _ = state.channel.resolve_session(x_twin_session, _client_ip(request))
            state.channel.heartbeat(sess)
        except TwinChannelError as e:
            raise _twin_channel_error(e)

    @app.get("/twin/jobs/next", response_model=ToolCall)
    async def twin_jobs_next(request: Request,
                             x_twin_session: str | None = Header(default=None)):
        try:
            sess, row = state.channel.resolve_session(x_twin_session, _client_ip(request))
            call = await state.channel.next_job(sess, row, state.settings.twin_job_poll_s)
        except TwinChannelError as e:
            raise _twin_channel_error(e)
        if call is None:
            return Response(status_code=204)
        return call

    @app.post("/twin/jobs/{job_id}/result", status_code=204)
    async def twin_job_result(job_id: str, body: ToolResult, request: Request,
                              x_twin_session: str | None = Header(default=None)):
        try:
            sess, _ = state.channel.resolve_session(x_twin_session, _client_ip(request))
            state.channel.submit_result(sess, job_id, body)
        except TwinChannelError as e:
            raise _twin_channel_error(e)

    # ---------------------------------------------------------------- F9: approve
    @app.post("/cases/{case_id}/actions/{action_id}/approve",
              response_model=Action, status_code=200)
    async def approve_action(case_id: str, action_id: str, body: ApproveRequest,
                             operator: str = Depends(require_human)):
        try:
            # approval applies the action immediately (endpoint contract);
            # apply_action returns the action with its API response
            await state.service.approve_action(case_id, action_id, operator)
            return await state.service.apply_action(case_id, action_id)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ActionConflict as e:
            raise HTTPException(409, str(e))

    @app.post("/cases/{case_id}/actions", response_model=Action, status_code=201)
    async def add_custom_action(case_id: str, body: CustomActionRequest,
                                _: str = Depends(require_human)):
        try:
            return await state.service.add_custom_action(case_id, body)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except TransitionError as e:
            raise HTTPException(409, str(e))

    # ---------------------------------------------------------------- F11: teardown
    @app.post("/cases/{case_id}/close", response_model=CaseDetail)
    async def close_case(case_id: str, _: str = Depends(require_human)):
        try:
            await state.service.close_case(case_id)
            return state.service.detail(case_id)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except TransitionError as e:
            raise HTTPException(409, str(e))

    # ---------------------------------------------------------------- F14: evidence bundle
    @app.get("/cases/{case_id}/bundle")
    async def evidence_bundle(case_id: str, _: str = Depends(require_human)):
        try:
            content = state.service.evidence_bundle(case_id)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ValueError as e:
            raise HTTPException(409, str(e))
        return Response(
            content=content,
            media_type="application/zip",
            headers={"Content-Disposition":
                     f'attachment; filename="body-double-{case_id}.zip"'},
        )

    return app


# `uvicorn backend.app:app --reload` (state assembled from env at import)
app = create_app()
