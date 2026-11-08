"""Shared fixtures: a real AppState on a throwaway SQLite DB with FakeVultr
and tiny timeouts, plus an in-process httpx client.

Twin-channel tests need to control the *source address* of requests (the
channel only accepts calls from the case's VPC subnet), so `make_src_client`
wraps the ASGI app with a spoofed scope["client"]. `open_env` builds a
state + client with settings overrides (no fake twin, tiny timeouts, ...).
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager

import httpx
import pytest

from backend.config import test_settings
from backend.state import build_state


class _SpoofedClient:
    """ASGI wrapper that forces a specific source IP on every request."""

    def __init__(self, app, ip: str):
        self.app = app
        self.ip = ip

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            scope["client"] = (self.ip, 50000)
        await self.app(scope, receive, send)


async def _cancel_fake_twins(st) -> None:
    """Stop in-process twin stand-ins before the event loop goes away."""
    for t in st.fake_twin_tasks.values():
        t.cancel()
    await asyncio.gather(*st.fake_twin_tasks.values(), return_exceptions=True)
    st.fake_twin_tasks.clear()


@pytest.fixture
async def state(tmp_path):
    settings = test_settings(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    st = build_state(settings)
    yield st
    await _cancel_fake_twins(st)
    st.close()


@pytest.fixture
def app(state):
    return state.app


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


def make_src_client(app, ip: str) -> httpx.AsyncClient:
    """An httpx client whose requests appear to come from `ip`."""
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=_SpoofedClient(app, ip)),
                             base_url="http://t")


@asynccontextmanager
async def open_env(tmp_path, fake=None, **overrides):
    """A state + client pair on a throwaway DB with settings overrides, with a
    pre-minted human session. Used instead of the `state`/`client` fixtures
    when a test needs a non-default setting (e.g. no fake twin)."""
    settings = test_settings(f"sqlite:///{(tmp_path / 't.db').as_posix()}")
    for k, v in overrides.items():
        setattr(settings, k, v)
    st = build_state(settings, vultr=fake)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=st.app),
                                base_url="http://t") as client:
        r = await client.post("/auth/session", json={"operator": "operator"})
        client.headers["X-Human-Session"] = r.json()["session_token"]
        try:
            yield st, client
        finally:
            await _cancel_fake_twins(st)
            st.close()


@pytest.fixture
def fake(state):
    return state.vultr


@pytest.fixture
async def human(client):
    """Headers carrying a valid human (operator) session."""
    r = await client.post("/auth/session", json={"operator": "operator"})
    assert r.status_code == 200, r.text
    return {"X-Human-Session": r.json()["session_token"]}
