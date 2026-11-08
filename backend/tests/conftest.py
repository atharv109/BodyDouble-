"""Shared fixtures: a real AppState on a throwaway SQLite DB with FakeVultr
and tiny timeouts, plus an in-process httpx client.

Twin-channel tests need to control the *source address* of requests (the
channel only accepts calls from the case's VPC subnet), so `make_src_client`
wraps the ASGI app with a spoofed scope["client"].
"""
from __future__ import annotations

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


@pytest.fixture
def state(tmp_path):
    settings = test_settings(f"sqlite:///{(tmp_path / 'test.db').as_posix()}")
    st = build_state(settings)
    yield st
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


@pytest.fixture
def fake(state):
    return state.vultr


@pytest.fixture
async def human(client):
    """Headers carrying a valid human (operator) session."""
    r = await client.post("/auth/session", json={"operator": "operator"})
    assert r.status_code == 200, r.text
    return {"X-Human-Session": r.json()["session_token"]}
