"""Api.delete_until_gone: a 409 'Server is currently locked' is not 'deleted'
(W2 leaked instance fb0dd8a4 by treating one 409 as done)."""
from __future__ import annotations

import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from bdvultr import Api  # noqa: E402


def api_with(statuses: list[int]) -> tuple[Api, list[int]]:
    seen: list[int] = []

    def handler(req: httpx.Request) -> httpx.Response:
        s = statuses[min(len(seen), len(statuses) - 1)]
        seen.append(s)
        return httpx.Response(s, json={"error": "Server is currently locked"} if s >= 400 else None)

    return Api("k", transport=httpx.MockTransport(handler)), seen


def test_retries_locked_until_deleted():
    api, seen = api_with([409, 409, 204])
    assert api.delete_until_gone("/v2/instances/x", every_s=0) == 204
    assert seen == [409, 409, 204]


def test_404_counts_as_gone():
    api, seen = api_with([404])
    assert api.delete_until_gone("/v2/instances/x", every_s=0) == 404


def test_still_locked_at_timeout_raises():
    api, _ = api_with([409])
    with pytest.raises(RuntimeError, match="still failing"):
        api.delete_until_gone("/v2/instances/x", timeout_s=0, every_s=0)
