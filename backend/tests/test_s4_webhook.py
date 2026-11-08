from __future__ import annotations

import json

from contracts.hashing import sensor_signature
from contracts.models import ALERTS_PER_INSTANCE_PER_MIN


def _payload(summary: str = "Falco shell alert", source: str = "falco") -> bytes:
    return json.dumps({
        "instance_id": "inst-shop-prod",
        "source": source,
        "summary": summary,
        "detail": {"rule": "Terminal shell in container"},
    }, separators=(",", ":")).encode()


async def _send(client, raw: bytes, secret: str | None):
    headers = {"Content-Type": "application/json"}
    if secret is not None:
        headers["X-BD-Signature"] = sensor_signature(secret, raw)
    return await client.post("/alerts/webhook", content=raw, headers=headers)


async def test_webhook_is_404_when_unset_and_rejects_bad_signatures(
        client, state):
    raw = _payload()
    assert (await _send(client, raw, "anything")).status_code == 404

    state.settings.webhook_secret = "shared-webhook-secret"
    assert (await _send(client, raw, None)).status_code == 401
    assert (await _send(client, raw, "wrong-secret")).status_code == 401


async def test_webhook_creates_external_alert_rate_limits_and_lists_newest(
        client, state, human):
    secret = "shared-webhook-secret"
    state.settings.webhook_secret = secret
    created = []
    for index in range(ALERTS_PER_INSTANCE_PER_MIN):
        response = await _send(client, _payload(f"alert {index}"), secret)
        assert response.status_code == 200, response.text
        created.append(response.json())
    assert created[0]["signal"] == "external"
    assert created[0]["source"] == "falco"
    assert created[0]["case_id"]

    over = await _send(client, _payload("over limit"), secret)
    assert over.status_code == 429

    assert (await client.get("/alerts")).status_code == 401
    listing = await client.get("/alerts", headers=human)
    assert listing.status_code == 200
    ids = [item["id"] for item in listing.json()]
    assert ids == [item["id"] for item in reversed(created)]
