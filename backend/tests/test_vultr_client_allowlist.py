"""B0: raw `request()` allowlist pins every real call. (method, path) must be
on ALLOWED_RAW_CALLS, PATCH bodies may only carry firewall_group_id, and a
path is matched exactly — an absolute URL (host smuggling) or a query string
is refused by check_raw_call before any request leaves the process. The
RealVultr http client never follows redirects and talks to api.vultr.com only.

The transport here is an httpx.MockTransport wrapper, so no test touches the
network.
"""
from __future__ import annotations

import httpx
import pytest

from contracts.vultr import DisallowedCall, RealVultr, VultrNotFound


class RecordingTransport(httpx.MockTransport):
    """Wraps a plain (request -> Response) handler and records every URL the
    client actually tried to send, so refusals can be proven pre-network."""

    def __init__(self, handler):
        self.urls: list[str] = []
        self._handler = handler

        async def recording(request: httpx.Request) -> httpx.Response:
            self.urls.append(str(request.url))
            return handler(request)

        super().__init__(recording)


def make_real_with(transport: RecordingTransport) -> RealVultr:
    rv = RealVultr(api_key="test-key")
    assert str(rv._http.base_url).rstrip("/") == RealVultr.BASE  # host pinned
    rv._http = httpx.AsyncClient(
        transport=transport, base_url=RealVultr.BASE,
        follow_redirects=False,  # same construction config RealVultr uses
        headers={"Authorization": f"Bearer test-key"})
    return rv


def ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(202, json={"instance": {"id": "inst-1"}})


async def test_allowed_call_reaches_pinned_host():
    t = RecordingTransport(ok)
    rv = make_real_with(t)
    r = await rv.request("PATCH", "/v2/instances/inst-1",
                         {"firewall_group_id": "fw-1"})
    assert t.urls == ["https://api.vultr.com/v2/instances/inst-1"]
    assert r.status_code == 202


async def test_disallowed_method_is_refused_without_network():
    t = RecordingTransport(ok)
    rv = make_real_with(t)
    with pytest.raises(DisallowedCall):
        await rv.request("GET", "/v2/instances/inst-999")
    assert t.urls == []  # refused before leaving the process


async def test_path_off_the_menu_is_refused():
    t = RecordingTransport(ok)
    rv = make_real_with(t)
    with pytest.raises(DisallowedCall):
        await rv.request("POST", "/v2/instances/inst-1/iso/attach", {"iso_id": "iso1"})
    with pytest.raises(DisallowedCall):
        await rv.request("PATCH", "/v2/instances/inst-1/something")
    with pytest.raises(DisallowedCall):
        await rv.request("PATCH", "/v2/instances/inst-1?x=1")  # query smuggled in
    assert t.urls == []


async def test_absolute_url_host_smuggling_is_refused():
    t = RecordingTransport(ok)
    rv = make_real_with(t)
    with pytest.raises(DisallowedCall):
        await rv.request("POST", "https://evil.example.com/v2/instances/inst-1/halt")
    assert t.urls == []


async def test_patch_body_keys_are_allowlisted():
    t = RecordingTransport(ok)
    rv = make_real_with(t)
    with pytest.raises(DisallowedCall):
        await rv.request("PATCH", "/v2/instances/inst-1",
                         {"firewall_group_id": "fw-1", "tag": "evil"})
    with pytest.raises(DisallowedCall):
        await rv.request("PATCH", "/v2/instances/inst-1", {})
    assert t.urls == []


async def test_real_client_never_follows_redirects():
    calls = []

    def redirect_then_pwn(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if "evil" not in (request.url.host or ""):
            return httpx.Response(302, headers={"Location": "https://evil.example.com/v2/final"})
        return httpx.Response(200, json={"pwned": True})

    t = RecordingTransport(redirect_then_pwn)
    rv = make_real_with(t)
    r = await rv.request("PATCH", "/v2/instances/inst-1", {"firewall_group_id": "fw-1"})
    assert r.status_code == 302  # the redirect is returned to the caller, not followed
    assert calls == ["https://api.vultr.com/v2/instances/inst-1"]
    # and a raw call to any other host is refused before it leaves the process
    with pytest.raises(DisallowedCall):
        await rv.request("POST", "https://evil.example.com/v2/instances/inst-1/halt")


async def test_typed_methods_pin_the_host_and_map_404():
    t = RecordingTransport(lambda request: httpx.Response(404, text="Not Found"))
    rv = make_real_with(t)
    # every typed call stays on api.vultr.com even when the resource 404s
    with pytest.raises(VultrNotFound):
        await rv.get_snapshot("snap-gone")
    assert t.urls == ["https://api.vultr.com/v2/snapshots/snap-gone"]
