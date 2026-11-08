from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path


ROOT = Path(__file__).parents[2]
SENSOR = ROOT / "sensor" / "bd-sensor.sh"


def test_sensor_is_posix_push_only_and_covers_required_paths() -> None:
    text = SENSOR.read_text()
    assert text.startswith("#!/bin/sh\n")
    assert "#!/bin/bash" not in text
    assert "curl" in text and "-o /dev/null" in text
    assert "openssl dgst -sha256 -hmac" in text
    assert "eval " not in text
    assert "nc " not in text and "socat" not in text
    for path in (
        "/etc/crontab",
        "/etc/cron.d/*",
        "/var/spool/cron/*",
        "/root/.ssh/authorized_keys",
        "/home/*/.ssh/authorized_keys",
        "/usr/bin/top",
        "/usr/bin/ps",
        "/usr/bin/ls",
        "/usr/bin/ss",
        "/usr/bin/netstat",
        "/usr/local/bin/*",
    ):
        assert path in text


def test_json_byte_escaping_handles_hostile_file_names() -> None:
    hostile = 'bad"\\\n\tname'
    encoded = '"' + "".join(f"\\u{byte:04x}" for byte in hostile.encode()) + '"'
    assert json.loads(encoded) == hostile
    assert "json_quote \"$path\"" in SENSOR.read_text()


def test_signature_algorithm_matches_contract() -> None:
    token = "ab" * 32
    body = b'{"hostile":"quote\\\" and newline\\n"}'
    expected = hmac.new(token.encode(), body, hashlib.sha256).hexdigest()
    from contracts.hashing import sensor_signature

    assert expected == sensor_signature(token, body)


def test_conf_permission_and_owner_refusal_are_enforced() -> None:
    text = SENSOR.read_text()
    assert 'owner=$(stat -c %u "$CONF"' in text
    assert '[ "$owner" = 0 ]' in text
    assert 'mode=$(stat -c %a "$CONF"' in text
    assert '[ "$mode" = 600 ]' in text
