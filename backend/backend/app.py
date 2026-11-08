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

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response
from fastapi.responses import StreamingResponse

from contracts.models import (
    Action,
    ApproveRequest,
    Case,
    CaseDetail,
    OpenCaseRequest,
    ToolCall,
    ToolResult,
    TwinRegisterRequest,
    TwinRegisterResponse,
)
from contracts.vultr import VultrError

from .sessions import mint, verify
from .state import AppState, build_state
from .service import ActionConflict, TransitionError
from .twin import TwinChannelError

COOKIE_NAME = "bd_session"


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else ""


def _twin_channel_error(e: TwinChannelError) -> HTTPException:
    return HTTPException(e.status_code, e.detail)


async def get_operator(
    request: Request,
    bd_session: str | None = Cookie(default=None),
) -> str | None:
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

    @app.get("/healthz", include_in_schema=False)
    async def healthz():
        return {"ok": True, "vultr": "fake" if state.is_fake else "real"}

    # ---------------------------------------------------------------- auth
    @app.post("/auth/session")
    async def create_session(body: dict, response: Response):
        operator = (body or {}).get("operator", "").strip()
        if not operator or len(operator) > 64:
            raise HTTPException(422, "operator name required (1-64 chars)")
        token = mint(operator, state.settings.app_secret, state.settings.session_ttl_s)
        response.set_cookie(COOKIE_NAME, token, httponly=True, samesite="lax")
        return {"operator": operator, "session_token": token}

    # ---------------------------------------------------------------- F1
    @app.get("/instances", dependencies=[Depends(require_human)])
    async def list_instances():
        return await state.vultr.list_instances()

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

    @app.get("/cases/{case_id}", response_model=CaseDetail,
             dependencies=[Depends(require_human)])
    async def get_case(case_id: str):
        try:
            return state.service.detail(case_id)
        except LookupError as e:
            raise HTTPException(404, str(e))

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
        if body.approved_by != operator:
            raise HTTPException(422, "approved_by must match your session operator")
        try:
            # approval applies the action immediately (endpoint contract);
            # apply_action returns the action with its API response
            await state.service.approve_action(case_id, action_id, operator)
            return await state.service.apply_action(case_id, action_id)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ActionConflict as e:
            raise HTTPException(409, str(e))

    # ---------------------------------------------------------------- F11: teardown
    @app.post("/cases/{case_id}/close", response_model=Case)
    async def close_case(case_id: str, _: str = Depends(require_human)):
        try:
            return await state.service.close_case(case_id)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except TransitionError as e:
            raise HTTPException(409, str(e))

    return app


# `uvicorn backend.app:app --reload` (state assembled from env at import)
app = create_app()
