"""demo/plant.sh: running it in a debian container yields the same 5
indicators as demo/victim/ (TASK.md "Done when").

Docker-gated: skips when no docker daemon is reachable, so the rest of the
suite still runs on machines without one.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest

from bd_forensics.indicators import INDICATORS

REPO = Path(__file__).resolve().parents[2]
VICTIM = REPO / "demo" / "victim"

INSPECT = r"""
# debian:12-slim ships without procps; install it so the planted "replaced top"
# is a real package binary with a real dpkg record to mismatch against.
apt-get update >/dev/null 2>&1 || true
apt-get install -y --no-install-recommends procps >/dev/null 2>&1
command -v top >/dev/null || { echo "procps install failed" >&2; exit 3; }
sh /demo-src/demo/plant.sh
echo "---HASHES---"
sha256sum /etc/cron.d/bdrv /root/.ssh/authorized_keys /usr/bin/top /usr/local/bin/.bdrv /var/backups/notes-to-ai.txt
echo "---TOP---"
echo "TOP_ON_DISK=$(md5sum /usr/bin/top | cut -d' ' -f1)"
echo "TOP_RECORDED=$(grep 'usr/bin/top$' /var/lib/dpkg/info/procps.md5sums 2>/dev/null | cut -d' ' -f1)"
"""


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True, timeout=60).returncode == 0


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not reachable")
def test_plant_yields_the_same_five_indicators() -> None:
    name = f"bd-plant-{uuid.uuid4().hex[:8]}"
    out = subprocess.run(
        [
            "docker", "run", "--rm", "--name", name,
            "-e", "BD_PLANT_DEMO=1",  # plant.sh consent guard
            "-v", f"{REPO.as_posix()}:/demo-src:ro",
            "debian:12-slim", "sh", "-c", INSPECT,
        ],
        capture_output=True, text=True, timeout=600,
    )
    assert out.returncode == 0, out.stderr

    lines = out.stdout.splitlines()
    i = lines.index("---HASHES---")
    j = lines.index("---TOP---")
    container_hashes: dict[str, str] = {}
    for line in lines[i + 1 : j]:
        h, p = line.split()
        container_hashes[p] = h

    for path in INDICATORS:
        local = hashlib.sha256((VICTIM / path.lstrip("/")).read_bytes()).hexdigest()
        assert container_hashes.get(path) == local, f"{path} differs from demo/victim/"
    assert len(container_hashes) == 5

    # indicator 3 must be a real indicator: checksum changed vs the dpkg record
    top = dict(line.split("=", 1) for line in lines[j + 1 :])
    assert top["TOP_ON_DISK"] != top["TOP_RECORDED"], "planted top must not match the dpkg record"
    assert top["TOP_RECORDED"] not in ("", "missing"), "container had no dpkg record for procps top"


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not reachable")
def test_plant_refuses_without_consent() -> None:
    """No BD_PLANT_DEMO=1: the script must refuse and plant nothing."""
    out = subprocess.run(
        [
            "docker", "run", "--rm",
            "-v", f"{REPO.as_posix()}:/demo-src:ro",
            "debian:12-slim", "sh", "/demo-src/demo/plant.sh",
        ],
        capture_output=True, text=True, timeout=300,
    )
    assert out.returncode == 99, "plant.sh must refuse without BD_PLANT_DEMO=1"
    assert "BD_PLANT_DEMO" in out.stderr
