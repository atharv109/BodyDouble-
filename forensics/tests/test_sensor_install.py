from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
INSTALL = ROOT / "sensor" / "install.sh"
TEMPLATE = ROOT / "sensor" / "install.in.sh"
SENSOR = ROOT / "sensor" / "bd-sensor.sh"


def test_generated_installer_is_self_contained_and_current() -> None:
    generated = INSTALL.read_text()
    assert "__BD_SENSOR_PAYLOAD__" not in generated
    assert SENSOR.read_text().rstrip() in generated
    assert generated.startswith("#!/bin/sh\n")


def test_installer_strictly_validates_all_arguments() -> None:
    text = TEMPLATE.read_text()
    assert '[ "$#" -eq 3 ]' in text
    assert "^https://" in text
    assert "localhost|127\\.0\\.0\\.1" in text
    assert "^[A-Za-z0-9-]{1,64}$" in text
    assert "^[A-Fa-f0-9]{64}$" in text
    assert "eval " not in text


def test_installer_hardens_config_and_service() -> None:
    text = INSTALL.read_text()
    assert 'chown root:root "$conf_tmp"' in text
    assert 'chmod 600 "$conf_tmp"' in text
    for directive in (
        "NoNewPrivileges=yes",
        "ProtectHome=read-only",
        "PrivateTmp=yes",
        "ReadOnlyPaths=/",
        "ReadWritePaths=/var/lib/body-double/sensor",
    ):
        assert directive in text
    assert '"$SENSOR" --once' in text
    assert "systemctl enable --now bd-sensor.service" in text


def test_uninstall_is_idempotent_and_scoped() -> None:
    text = TEMPLATE.read_text()
    assert "--uninstall" in text
    assert 'rm -f "$UNIT" "$SENSOR" "$CONF"' in text
    assert 'rm -rf "$STATE"' in text
    assert not re.search(r"rm -rf [~/]($|[ ;])", text)


@pytest.mark.parametrize(
    "args",
    [
        [],
        ["ftp://example.com", "server-1", "ab" * 32],
        ["http://example.com", "server-1", "ab" * 32],
        ["https://example.com", "bad_instance", "ab" * 32],
        ["https://example.com", "server-1", "not-a-token"],
        ["https://example.com", "server-1", "ab" * 31],
        ["--uninstall", "extra"],
    ],
)
def test_bad_arguments_are_refused_in_debian(args: list[str]) -> None:
    result = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            f"{ROOT.as_posix()}:/src:ro",
            "debian:12",
            "sh",
            "/src/sensor/install.sh",
            *args,
        ],
        text=True,
        capture_output=True,
        timeout=60,
    )
    assert result.returncode != 0
    assert "installer:" in result.stderr
