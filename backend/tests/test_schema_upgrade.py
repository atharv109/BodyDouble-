from __future__ import annotations

import asyncio

import httpx
from sqlalchemy import create_engine, inspect, text

from backend.config import test_settings as make_test_settings
from backend.db import ActionRow, init_db
from backend.state import build_state


def _create_pre_plug_and_play_database(url: str) -> None:
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("""
            CREATE TABLE cases (
                id VARCHAR(32) PRIMARY KEY,
                instance_id VARCHAR(64) NOT NULL,
                instance_label VARCHAR(128) NOT NULL,
                reason TEXT NOT NULL,
                state VARCHAR(16) NOT NULL,
                snapshot_id VARCHAR(64), twin_instance_id VARCHAR(64),
                vpc_id VARCHAR(64), firewall_group_id VARCHAR(64),
                created_at DATETIME NOT NULL, closed_at DATETIME,
                operator VARCHAR(64) NOT NULL DEFAULT 'operator',
                reg_token VARCHAR(128), twin_internal_ip VARCHAR(64),
                vpc_subnet VARCHAR(64), vpc_mask INTEGER,
                quarantine_group_id VARCHAR(64), seal JSON, blast_radius JSON
            )
        """))
        connection.execute(text("""
            CREATE TABLE actions (
                id VARCHAR(64) PRIMARY KEY,
                case_id VARCHAR(32) NOT NULL,
                kind VARCHAR(32) NOT NULL,
                target VARCHAR(64) NOT NULL,
                api_method VARCHAR(8), api_path VARCHAR(255), api_body JSON,
                description TEXT NOT NULL,
                status VARCHAR(16) NOT NULL DEFAULT 'proposed',
                approved_by VARCHAR(64), response JSON
            )
        """))
        connection.execute(text("""
            INSERT INTO cases
                (id, instance_id, instance_label, reason, state, created_at, operator)
            VALUES
                ('case-0001', 'inst-clean-control', 'clean-control',
                 'old case must survive', 'closed', '2026-11-01 00:00:00', 'legacy')
        """))
        connection.execute(text("""
            INSERT INTO actions
                (id, case_id, kind, target, description, status)
            VALUES
                ('old-action', 'case-0001', 'stop_instance', 'inst-clean-control',
                 'old action must survive', 'proposed')
        """))
    engine.dispose()


async def test_startup_upgrades_pre_plug_and_play_schema_without_data_loss(tmp_path):
    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    _create_pre_plug_and_play_database(url)
    before = create_engine(url)
    assert "alert_id" not in {c["name"] for c in inspect(before).get_columns("cases")}
    assert "recommended" not in {c["name"] for c in inspect(before).get_columns("actions")}
    assert "sensors" not in inspect(before).get_table_names()
    before.dispose()

    state = build_state(make_test_settings(url))
    try:
        # Existing rows remain readable, with safe defaults in newly added columns.
        old_case = state.service.model("case-0001")
        assert old_case.reason == "old case must survive"
        assert old_case.alert_id is None
        with state.sf() as session:
            old_action = session.get(ActionRow, "old-action")
            assert old_action.description == "old action must survive"
            assert old_action.recommended is False
            assert old_action.created_by == "agent"

        upgraded = inspect(state.engine)
        assert {"sensors", "alerts", "sensor_nonces"}.issubset(
            upgraded.get_table_names())
        assert "alert_id" in {c["name"] for c in upgraded.get_columns("cases")}
        assert {"recommended", "created_by"}.issubset(
            c["name"] for c in upgraded.get_columns("actions"))
        init_db(state.engine)  # repeated startup is a no-op

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=state.app), base_url="http://t"
        ) as client:
            auth = await client.post("/auth/session", json={"operator": "operator"})
            headers = {"X-Human-Session": auth.json()["session_token"]}
            infected = await client.post("/dev/infect", headers=headers,
                                         json={"attacks": ["cron_backdoor"]})
            assert infected.status_code == 201, infected.text
            assert infected.json()["case_id"] == "case-0002"
        assert state.service.model("case-0001").reason == "old case must survive"
    finally:
        for task in state.fake_twin_tasks.values():
            task.cancel()
        await asyncio.gather(*state.fake_twin_tasks.values(), return_exceptions=True)
        state.close()
