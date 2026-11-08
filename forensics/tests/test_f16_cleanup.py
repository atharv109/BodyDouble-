"""F16: sandbox results expose zero residual blast radius."""
from __future__ import annotations

import shutil
import subprocess
import uuid

import pytest

from contracts.models import ToolCall, ToolName
from bd_forensics.sandbox import detonate, run_custom_script
from conftest import VICTIM


def _docker_available() -> bool:
    return bool(shutil.which("docker")) and subprocess.run(
        ["docker", "info"], capture_output=True, timeout=60
    ).returncode == 0


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not reachable")
@pytest.mark.parametrize("tool", [ToolName.detonate, ToolName.custom_script])
def test_sandbox_result_reports_no_containers_or_packets_left(tool) -> None:
    job_id = f"cleanup-{uuid.uuid4().hex[:8]}"
    if tool == ToolName.detonate:
        call = ToolCall(job_id=job_id, case_id="case-1", tool=tool,
                        args={"path": "/usr/local/bin/.bdrv"})
        result = detonate(call, str(VICTIM))
    else:
        call = ToolCall(job_id=job_id, case_id="case-1", tool=tool,
                        args={"code": "open('/tmp/f16', 'w').write('stand-in')"})
        result = run_custom_script(call, str(VICTIM))

    assert result.exit_code == 0, result.stderr
    assert result.containers_left == 0
    assert result.packets_out == 0
    remaining = subprocess.run(
        ["docker", "ps", "-a", "--filter", f"name=bd-det-{job_id}", "-q"],
        capture_output=True, text=True, check=True, timeout=60,
    )
    assert remaining.stdout.strip() == ""
