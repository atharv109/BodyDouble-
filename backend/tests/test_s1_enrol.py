from __future__ import annotations

import hashlib
import re
from pathlib import Path

from backend.db import SensorRow


async def test_enrol_rotates_token_and_persists_only_sha256(client, state, human):
    state.settings.public_url = "https://bd.example"
    first = await client.post("/sensors", headers=human,
                              json={"instance_id": "inst-shop-prod"})
    assert first.status_code == 200, first.text
    body = first.json()
    assert re.fullmatch(r"[0-9a-f]{64}", body["token"])
    command = ("curl -fsSL https://bd.example/api/sensors/install.sh | sudo sh -s -- "
               f"https://bd.example inst-shop-prod {body['token']}")
    assert body["install_command"] == command
    assert body["startup_script"] == f"#!/bin/sh\n{command}\n"

    with state.sf() as session:
        row = session.get(SensorRow, "inst-shop-prod")
        assert row.token_sha256 == hashlib.sha256(body["token"].encode()).hexdigest()
        assert body["token"] not in row.token_sha256

    second = await client.post("/sensors", headers=human,
                               json={"instance_id": "inst-shop-prod"})
    assert second.status_code == 200
    assert second.json()["token"] != body["token"]
    with state.sf() as session:
        row = session.get(SensorRow, "inst-shop-prod")
        assert row.token_sha256 == hashlib.sha256(
            second.json()["token"].encode()).hexdigest()


async def test_sensor_list_unknown_instance_and_public_installer(client, human):
    missing = await client.post("/sensors", headers=human,
                                json={"instance_id": "inst-does-not-exist"})
    assert missing.status_code == 404

    enrolled = await client.post("/sensors", headers=human,
                                 json={"instance_id": "inst-shop-prod"})
    assert enrolled.status_code == 200
    listing = await client.get("/sensors", headers=human)
    assert listing.status_code == 200
    assert listing.json() == [{
        "instance_id": "inst-shop-prod",
        "enrolled_at": listing.json()[0]["enrolled_at"],
        "last_seen": None,
        "healthy": False,
    }]

    installer_path = Path(__file__).resolve().parents[2] / "sensor" / "install.sh"
    installer = await client.get("/sensors/install.sh")
    if installer_path.is_file():
        assert installer.status_code == 200
        assert installer.headers["content-type"].startswith("text/x-shellscript")
        assert installer.content == installer_path.read_bytes()
    else:
        assert installer.status_code == 404
