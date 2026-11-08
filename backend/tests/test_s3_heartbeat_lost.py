from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from contracts.hashing import sensor_signature
from contracts.models import HEARTBEAT_LOST_S

from backend.db import AlertRow, SensorRow


async def test_watcher_raises_exactly_one_alert_per_lapse(client, state, human):
    enrolled = await client.post("/sensors", headers=human,
                                 json={"instance_id": "inst-shop-prod"})
    token = enrolled.json()["token"]
    base = datetime(2026, 11, 8, 12, 0, 0)
    with state.sf() as session:
        sensor = session.get(SensorRow, "inst-shop-prod")
        sensor.enrolled_at = base
        session.commit()

    state.clock = lambda: base + timedelta(seconds=HEARTBEAT_LOST_S + 1)
    first = await state.service.check_heartbeat_losses()
    assert len(first) == 1
    assert first[0].signal.value == "heartbeat_lost"
    assert first[0].source == "control_plane"
    assert first[0].case_id
    assert (await client.get(f"/cases/{first[0].case_id}", headers=human)).json()[
        "case"]["state"] == "reported"

    assert await state.service.check_heartbeat_losses() == []
    with state.sf() as session:
        alerts = list(session.execute(select(AlertRow)).scalars())
    assert len(alerts) == 1

    heartbeat_at = base + timedelta(seconds=HEARTBEAT_LOST_S + 20)
    state.clock = lambda: heartbeat_at
    raw = json.dumps({
        "instance_id": "inst-shop-prod",
        "sent_at": heartbeat_at.replace(tzinfo=timezone.utc).isoformat(),
        "nonce": "recoveredbeat001",
    }, separators=(",", ":")).encode()
    response = await client.post("/sensors/heartbeat", content=raw, headers={
        "Content-Type": "application/json",
        "X-BD-Signature": sensor_signature(token, raw),
    })
    assert response.status_code == 204

    state.clock = lambda: heartbeat_at + timedelta(seconds=HEARTBEAT_LOST_S + 1)
    second = await state.service.check_heartbeat_losses()
    assert len(second) == 1
    assert second[0].case_id == first[0].case_id  # attaches to the live reported case
    assert await state.service.check_heartbeat_losses() == []
    with state.sf() as session:
        alerts = list(session.execute(select(AlertRow).order_by(AlertRow.received_at)).scalars())
    assert [alert.signal for alert in alerts] == ["heartbeat_lost", "heartbeat_lost"]
