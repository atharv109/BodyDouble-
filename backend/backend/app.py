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

from fastapi import Cookie, Depends, FastAPI, Header, HTTPException, Request, Response

from contracts.models import (
    Action,
    ApproveRequest,
    Case,
    OpenCaseRequest,
    ToolCall,
    ToolResult,
    TwinRegisterRequest,
    TwinRegisterResponse,
)
from contracts.vultr import VultrError

from .sessions import mint, verify
from .state import AppState, build_state
from .service import ActionConflict
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
            # F10 turns approval into the actual apply; for now it only
            # marks the action approved — nothing touches production.
            return await state.service.approve_action(case_id, action_id, operator)
        except LookupError as e:
            raise HTTPException(404, str(e))
        except ActionConflict as e:
            raise HTTPException(409, str(e))

    return app


# `uvicorn backend.app:app --reload` (state assembled from env at import)
app = create_app()
