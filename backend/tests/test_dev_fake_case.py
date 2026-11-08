from __future__ import annotations

from pathlib import Path

import pytest

from contracts.events import EventName, parse_sse


@pytest.mark.asyncio
async def test_dev_fake_case_covers_every_fixture_event(client, human):
    response = await client.post("/dev/fake-case", headers=human, json={})
    assert response.status_code == 201, response.text
    case = response.json()
    assert case["state"] == "closed"

    stream = await client.get(f"/cases/{case['id']}/stream", headers=human)
    actual = parse_sse(stream.text)
    fixture = parse_sse(
        (Path(__file__).parents[2] / "contracts" / "fixtures" / "fake_case.sse")
        .read_text(encoding="utf-8")
    )
    actual_names = {name for name, _seq, _payload in actual}
    fixture_names = {name for name, _seq, _payload in fixture}
    assert actual_names == fixture_names == set(EventName)
