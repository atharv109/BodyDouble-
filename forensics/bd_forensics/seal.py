"""F5 seal checks: the twin verifies its own isolation before investigating.

Both checks run on the twin itself (the forensics ISO booted instead of the
cloned OS, so the results are trustworthy - the attacker's code never runs):
- disk_read_only: the cloned disk must be mounted with the `ro` option.
- egress_blocked: an outbound connection to the public internet must fail
  (the ISO egress firewall default-DROPs everything but the case VPC).
"""
from __future__ import annotations

import socket
from pathlib import Path

from contracts.models import SealStatus

MOUNTS_PATH = "/proc/mounts"
MOUNT_POINT = "/mnt/disk"  # where the forensics ISO mounts the cloned disk
EGRESS_PROBE_TARGETS = [("1.1.1.1", 53), ("8.8.8.8", 53)]


def check_disk_read_only(mount_point: str, mounts_text: str | None = None) -> tuple[bool, str]:
    """The cloned disk must be mounted read-only.

    Returns (passed, raw_output); raw_output is the mount-table line (or the
    failure reason) and is shown on screen via the seal_check SSE event.
    """
    if mounts_text is None:
        mounts_text = Path(MOUNTS_PATH).read_text()
    for line in mounts_text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[1] == mount_point:
            return ("ro" in parts[3].split(",")), line
    return False, f"{mount_point} not found in {MOUNTS_PATH}"


def internet_egress_probe(
    targets: list[tuple[str, int]] | None = None, timeout_s: float = 5.0
) -> tuple[bool, str]:
    """Try real outbound TCP connections to public internet hosts.

    Returns (egress_blocked, raw_output). If any target is reachable, the
    twin has internet egress - which must never happen.
    """
    outputs: list[str] = []
    for host, port in (targets or EGRESS_PROBE_TARGETS):
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                outputs.append(f"tcp {host}:{port} CONNECTED - egress is open")
        except OSError as exc:
            outputs.append(f"tcp {host}:{port} failed: {type(exc).__name__}: {exc}")
    blocked = all("CONNECTED" not in o for o in outputs)
    return blocked, "; ".join(outputs)


def seal_status(
    mount_point: str = MOUNT_POINT,
    mounts_text: str | None = None,
    egress: tuple[bool, str] | None = None,
) -> SealStatus:
    """Run both seal checks and build the SealStatus for registration."""
    ro, ro_raw = check_disk_read_only(mount_point, mounts_text)
    if egress is None:
        blocked, egress_raw = internet_egress_probe()
    else:
        blocked, egress_raw = egress
    return SealStatus(
        disk_read_only=ro,
        egress_blocked=blocked,
        detail={"disk_read_only": ro_raw, "egress_blocked": egress_raw},
    )
