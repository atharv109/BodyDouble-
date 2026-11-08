from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from contracts.hashing import sensor_signature
from contracts.models import ActionStatus, ALERTS_PER_INSTANCE_PER_MIN


async def _enrol(client, human, instance_id="inst-shop-prod") -> str:
    response = await client.post("/sensors", headers=human,
                                 json={"instance_id": instance_id})
    assert response.status_code == 200, response.text
    return response.json()["token"]


def _report(instance_id="inst-shop-prod", nonce="abcdefghijklmnop",
            sent_at: datetime | None = None, summary="cron changed") -> bytes:
    return json.dumps({
        "instance_id": instance_id,
        "signal": "file_changed",
        "summary": summary,
        "detail": {"path": "/etc/cron.d/backdoor"},
        "sent_at": (sent_at or datetime.now(timezone.utc)).isoformat(),
        "nonce": nonce,
    }, separators=(",", ":")).encode()


async def _post(client, raw: bytes, token: str | None):
    headers = {"Content-Type": "application/json"}
    if token is not None:
        headers["X-BD-Signature"] = sensor_signature(token, raw)
    return await client.post("/sensors/report", content=raw, headers=headers)


async def test_missing_bad_and_unknown_sensor_signatures_are_401(client, human):
    token = await _enrol(client, human)
    raw = _report()
    assert (await _post(client, raw, None)).status_code == 401
    assert (await _post(client, raw, token + "bad")).status_code == 401
    unknown = _report(instance_id="inst-unknown", nonce="unknownnonce00001")
    assert (await _post(client, unknown, "unknown-token")).status_code == 401


async def test_clock_skew_replay_and_rate_limit(client, human):
    token = await _enrol(client, human)
    old = _report(sent_at=datetime.now(timezone.utc) - timedelta(minutes=6))
    assert (await _post(client, old, token)).status_code == 401

    replay = _report(nonce="replaynonce000001")
    assert (await _post(client, replay, token)).status_code == 200
    assert (await _post(client, replay, token)).status_code == 409

    # One alert already exists. Fill the remainder of the per-minute allowance.
    for index in range(1, ALERTS_PER_INSTANCE_PER_MIN):
        raw = _report(nonce=f"ratelimit{index:07d}", summary=f"alert {index}")
        response = await _post(client, raw, token)
        assert response.status_code == 200, response.text
    over = _report(nonce="ratelimit9999999", summary="one too many")
    assert (await _post(client, over, token)).status_code == 429


async def test_valid_alert_opens_safe_reported_case_and_heartbeat_updates(
        client, state, fake, human):
    token = await _enrol(client, human)
    raw = _report(nonce="validreport00001")
    response = await _post(client, raw, token)
    assert response.status_code == 200, response.text
    alert = response.json()
    assert alert["source"] == "sensor"
    assert alert["case_id"]

    detail = (await client.get(f"/cases/{alert['case_id']}", headers=human)).json()
    assert detail["case"]["state"] == "reported"
    assert detail["case"]["alert_id"] == alert["id"]
    assert detail["actions"] == []
    assert not any(action["status"] in {
        ActionStatus.approved.value, ActionStatus.applied.value
    } for action in detail["actions"])
    production_path = "/v2/instances/inst-shop-prod"
    assert not any(
        (method == "PATCH" and path == production_path)
        or (method == "POST" and path == production_path + "/halt")
        for method, path, _body in fake.calls
    )
    assert state.service.blast_radius(alert["case_id"]).prod_writes_before_approval == 0

    heartbeat = json.dumps({
        "instance_id": "inst-shop-prod",
        "sent_at": datetime.now(timezone.utc).isoformat(),
        "nonce": "heartbeat0000001",
    }, separators=(",", ":")).encode()
    heart = await client.post("/sensors/heartbeat", content=heartbeat, headers={
        "Content-Type": "application/json",
        "X-BD-Signature": sensor_signature(token, heartbeat),
    })
    assert heart.status_code == 204
    sensors = (await client.get("/sensors", headers=human)).json()
    assert sensors[0]["last_seen"] is not None and sensors[0]["healthy"] is True
