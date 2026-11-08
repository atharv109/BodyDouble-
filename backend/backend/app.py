"""FastAPI control plane. All routes are thin: they pull AppState from
request.app.state.bd and delegate to CaseService / TwinChannel.

Endpoint shapes are owned here (TASK.md); every change is logged to
~/bd-bridge/to-frontend.md.
"""
from __future__ import annotations

from fastapi import FastAPI, HTTPException

from contracts.models import Case, OpenCaseRequest

from .state import AppState, build_state


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

    # ---------------------------------------------------------------- F1
    @app.get("/instances")
    async def list_instances():
        return await state.vultr.list_instances()

    @app.post("/cases", response_model=Case, status_code=201)
    async def open_case(body: OpenCaseRequest):
        try:
            case = await state.service.open_case(body.instance_id, body.reason)
        except LookupError as e:
            raise HTTPException(404, str(e))
        return await state.service.run_case(case.id)

    return app


# `uvicorn backend.app:app --reload` (state assembled from env at import)
app = create_app()
