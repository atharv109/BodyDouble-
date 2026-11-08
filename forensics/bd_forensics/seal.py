"""F5 seal checks: the twin verifies its own isolation before investigating.

Both checks run on the twin itself (the forensics ISO booted instead of the
cloned OS, so the results are trustworthy - the attacker's code never runs):
- disk_read_only: the cloned disk must be mounted with the `ro` option.
- egress_blocked: an outbound connection to the public internet must fail
  (the ISO egress firewall allows only the case control-plane IP and port).
"""
from __future__ import annotations

import socket
from pathlib import Path

from contracts.models import SealStatus

MOUNTS_PATH = "/proc/mounts"
MOUNTINFO_PATH = "/proc/self/mountinfo"  # encodes the mount hierarchy; preferred
MOUNT_POINT = "/mnt/disk"  # where the forensics ISO mounts the cloned disk
EGRESS_PROBE_TARGETS = [
    ("1.1.1.1", 53),
    ("8.8.8.8", 53),
    ("1.1.1.1", 443),
    ("9.9.9.9", 80),
    ("208.67.222.222", 443),
]


def _read_mount_table() -> str:
    """Prefer /proc/self/mountinfo; fall back to /proc/mounts. Fail closed
    (raise, caught by callers) when neither is readable."""
    for path in (MOUNTINFO_PATH, MOUNTS_PATH):
        try:
            return Path(path).read_text()
        except OSError:
            continue
    raise OSError("no mount table readable")


def _mount_cols(first_line: str) -> tuple[int, int]:
    """Auto-detect format: mountinfo starts with a numeric mount ID."""
    return (4, 5) if first_line.split()[0].isdigit() else (1, 3)


def check_disk_read_only(mount_point: str, mounts_text: str | None = None) -> tuple[bool, str]:
    """The cloned disk and every mount under it must be read-only.

    Stacked or descendant mounts count too: any `rw` entry at or under the
    mount point fails the check (fail closed when nothing matches).
    Returns (passed, raw_output) for the seal_check SSE event.
    """
    if mounts_text is None:
        mounts_text = _read_mount_table()
    lines = mounts_text.splitlines()
    mp_i, opt_i = _mount_cols(lines[0]) if lines else (1, 3)
    prefix = mount_point.rstrip("/") + "/"
    is_mountinfo = bool(lines) and lines[0].split()[0].isdigit()
    relevant: list[tuple[str, str, str]] = []  # (mountpoint, options, device)
    for line in lines:
        parts = line.split()
        if len(parts) <= max(mp_i, opt_i):
            continue
        mp = parts[mp_i].replace("\\040", " ")
        if mp == mount_point or mp.startswith(prefix):
            device = parts[-2] if is_mountinfo and len(parts) >= 3 else parts[0]
            relevant.append((mp, parts[opt_i], device))
    if not relevant:
        return False, f"{mount_point} not found in the mount table"
    raw = "; ".join(f"{device} on {mp}: {opts}" for mp, opts, device in relevant)
    writable = [mp for mp, opts, _dev in relevant if "ro" not in opts.split(",")]
    if writable:
        return False, f"writable mounts under {mount_point}: {', '.join(writable)} | {raw}"
    return True, raw


def internet_egress_probe(
    targets: list[tuple[str, int]] | None = None, timeout_s: float = 3.0
) -> tuple[bool, str]:
    """Try real outbound TCP connections to public internet hosts, run
    concurrently so a sealed twin pays the timeout once, not per target.

    Returns (egress_blocked, raw_output). If any target is reachable, the
    twin has internet egress - which must never happen.
    """
    from concurrent.futures import ThreadPoolExecutor

    def probe(target: tuple[str, int]) -> str:
        host, port = target
        try:
            with socket.create_connection((host, port), timeout=timeout_s):
                return f"tcp {host}:{port} CONNECTED - egress is open"
        except OSError as exc:
            return f"tcp {host}:{port} failed: {type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=8) as pool:
        outputs = list(pool.map(probe, targets or EGRESS_PROBE_TARGETS))
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
