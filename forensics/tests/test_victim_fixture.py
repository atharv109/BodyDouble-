"""Victim fixture: demo/victim/ is the disk state demo/plant.sh produces."""
from __future__ import annotations

import hashlib
from pathlib import Path

from bd_forensics.indicators import INDICATORS

REPO = Path(__file__).resolve().parents[2]
VICTIM = REPO / "demo" / "victim"


def test_tree_lists_all_five_indicators() -> None:
    """Every planted indicator path exists and carries its marker content."""
    assert VICTIM.is_dir(), f"missing victim fixture at {VICTIM}"
    assert len(INDICATORS) == 5
    for path, marker in INDICATORS.items():
        f = VICTIM / path.lstrip("/")
        assert f.is_file(), f"missing indicator {path}"
        content = f.read_text()
        assert marker in content, f"{path} lacks marker {marker!r}"
        assert "\r" not in content, f"{path} has CRLF line endings"


def test_top_checksum_differs_from_dpkg_record() -> None:
    """usr/bin/top is replaced: its md5 no longer matches the package record."""
    top = (VICTIM / "usr/bin/top").read_bytes()
    recorded = (VICTIM / "var/lib/dpkg/info/procps.md5sums").read_text().split()[0]
    assert hashlib.md5(top).hexdigest() != recorded


def test_tree_is_a_linux_server_tree() -> None:
    """Enough of a real server that the triage tools have something to read."""
    for p in ("etc/passwd", "etc/os-release", "var/lib/dpkg/status", "var/log/auth.log"):
        assert (VICTIM / p).is_file(), f"missing {p}"
    assert "Debian" in (VICTIM / "etc/os-release").read_text()
    assert "shop-prod" in (VICTIM / "etc/hostname").read_text()
