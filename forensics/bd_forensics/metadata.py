"""Strict, Python-only twin bootstrap from Vultr instance metadata."""
from __future__ import annotations

import base64
import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import urlopen

METADATA_URL = "http://169.254.169.254/v1/user-data"
REQUIRED = {"case_id", "token", "control_plane", "vpc_subnet", "vpc_ip"}
SAFE_ID = re.compile(r"^[A-Za-z0-9-]{1,128}$")
NFT_IP_PLACEHOLDER = "__BD_CONTROL_PLANE_IP__"
NFT_PORT_PLACEHOLDER = "__BD_CONTROL_PLANE_PORT__"
NFT_PLACEHOLDERS = (NFT_IP_PLACEHOLDER, NFT_PORT_PLACEHOLDER)


def validate_bootstrap(payload: object) -> dict[str, str]:
    if not isinstance(payload, dict) or set(payload) != REQUIRED:
        raise ValueError("user_data must contain exactly the five bootstrap keys")
    if any(not isinstance(payload[key], str) for key in REQUIRED):
        raise ValueError("all bootstrap values must be strings")
    if not SAFE_ID.fullmatch(payload["case_id"]) or not SAFE_ID.fullmatch(payload["token"]):
        raise ValueError("case_id and token must match [A-Za-z0-9-]{1,128}")
    try:
        subnet = ipaddress.IPv4Network(payload["vpc_subnet"], strict=True)
        vpc_ip = ipaddress.IPv4Address(payload["vpc_ip"])
    except (ipaddress.AddressValueError, ipaddress.NetmaskValueError) as exc:
        raise ValueError("vpc_subnet and vpc_ip must be valid IPv4 values") from exc
    if vpc_ip not in subnet:
        raise ValueError("vpc_ip is outside vpc_subnet")
    cp = urlsplit(payload["control_plane"])
    if cp.scheme not in {"http", "https"} or cp.username or cp.password:
        raise ValueError("control_plane must be an HTTP(S) IPv4 URL")
    if cp.path not in {"", "/"} or cp.query or cp.fragment:
        raise ValueError("control_plane must not contain a path, query, or fragment")
    try:
        cp_ip = ipaddress.IPv4Address(cp.hostname or "")
        port = cp.port
    except (ipaddress.AddressValueError, ValueError) as exc:
        raise ValueError("control_plane host must be an IPv4 address with a port") from exc
    if port is None or cp_ip not in subnet:
        raise ValueError("control_plane IPv4:port must be inside vpc_subnet")
    return {
        "case_id": payload["case_id"], "token": payload["token"],
        "control_plane": payload["control_plane"],
        "vpc_subnet": str(subnet), "vpc_ip": str(vpc_ip),
    }


def decode_bootstrap(encoded: bytes) -> dict[str, str]:
    try:
        payload = json.loads(base64.b64decode(encoded.strip(), validate=True))
    except (ValueError, json.JSONDecodeError) as exc:
        raise ValueError("metadata user_data is not valid base64 JSON") from exc
    return validate_bootstrap(payload)


def fetch_bootstrap(url: str = METADATA_URL, timeout_s: float = 5.0) -> dict[str, str]:
    with urlopen(url, timeout=timeout_s) as response:  # noqa: S310 - fixed link-local URL
        return decode_bootstrap(response.read())


def drop_only_rules(template: str) -> str:
    return "\n".join(
        line for line in template.splitlines()
        if not any(placeholder in line for placeholder in NFT_PLACEHOLDERS)
    ) + "\n"


def configure_boot(metadata_url: str, nft_template: str | Path,
                   nft_output: str | Path, bootstrap_output: str | Path) -> dict[str, str]:
    """Write drop-only first; only validated data can add the control-plane rule."""
    template = Path(nft_template).read_text(encoding="utf-8")
    nft_path, bootstrap_path = Path(nft_output), Path(bootstrap_output)
    nft_path.write_text(drop_only_rules(template), encoding="utf-8")
    bootstrap_path.unlink(missing_ok=True)
    bootstrap = fetch_bootstrap(metadata_url)
    control_plane = urlsplit(bootstrap["control_plane"])
    rendered = template.replace(NFT_IP_PLACEHOLDER, control_plane.hostname or "")
    rendered = rendered.replace(NFT_PORT_PLACEHOLDER, str(control_plane.port))
    nft_path.write_text(rendered, encoding="utf-8")
    bootstrap_path.write_text(json.dumps(bootstrap), encoding="utf-8")
    bootstrap_path.chmod(0o600)
    return bootstrap


def load_bootstrap(path: str | Path) -> dict[str, str]:
    return validate_bootstrap(json.loads(Path(path).read_text(encoding="utf-8")))
