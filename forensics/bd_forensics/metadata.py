"""One-time twin bootstrap from Vultr instance metadata.

The control plane places base64(JSON) in user_data. This trusted bootstrap
is fetched before the ISO installs its default-DROP egress wall; no durable
image contains a registration token or control-plane address.
"""
from __future__ import annotations

import base64
import json
import shlex
from pathlib import Path
from urllib.request import urlopen

METADATA_URL = "http://169.254.169.254/v1/user-data"
REQUIRED = ("case_id", "token", "control_plane")


def fetch_bootstrap(url: str = METADATA_URL, timeout_s: float = 5.0) -> dict[str, str]:
    with urlopen(url, timeout=timeout_s) as response:  # noqa: S310 - fixed link-local URL
        encoded = response.read().strip()
    try:
        payload = json.loads(base64.b64decode(encoded, validate=True))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("metadata user_data is not valid base64 JSON") from exc
    if not isinstance(payload, dict):
        raise ValueError("metadata user_data must decode to an object")
    values = {name: payload.get(name) for name in REQUIRED}
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise ValueError("metadata user_data lacks case_id, token, or control_plane")
    return values  # type: ignore[return-value]


def write_agent_env(path: str | Path, bootstrap: dict[str, str]) -> None:
    """Write a shell-sourceable, injection-safe env file on tmpfs."""
    lines = {
        "BD_CASE_ID": bootstrap["case_id"],
        "BD_TOKEN": bootstrap["token"],
        "BD_CP": bootstrap["control_plane"],
    }
    Path(path).write_text(
        "".join(f"{key}={shlex.quote(value)}\n" for key, value in lines.items()),
        encoding="utf-8",
    )
