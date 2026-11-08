"""F7: detonate runs one extracted file in a no-network container (gVisor
runsc when the runtime is registered, else the documented docker fallback)
with a sinkhole resolver that answers and logs every DNS lookup; the
container is destroyed after each run; DNS lookups and file writes are
captured (the C2 lookup from the planted script appears).
"""
from __future__ import annotations

import hashlib
import importlib.util
import shutil
import socket
import struct
import subprocess
import threading
import uuid

import pytest

from contracts.models import ToolCall, ToolName
from bd_forensics import tools

from bd_forensics.sandbox import (
    RUNNER_CODE,
    WALL_CLOCK_S,
    _note,
    build_command,
    detonate,
    detect_runtime,
    run_custom_script,
)

from conftest import VICTIM


def _docker_available() -> bool:
    if not shutil.which("docker"):
        return False
    return subprocess.run(["docker", "info"], capture_output=True, timeout=60).returncode == 0


# ------------------------------------------------------------- no docker needed


def test_docker_command_carries_every_prd_limit() -> None:
    cmd = build_command("bd-det-job-1", "C:/w", "runc", WALL_CLOCK_S, "detonate")
    for pair in (
        ["--network", "none"], ["--dns", "127.0.0.1"],
        ["--cpus", "1"], ["--memory", "512m"], ["--pids-limit", "128"],
        ["--read-only"], ["--cap-drop", "ALL"],
        ["--security-opt", "no-new-privileges"],
        ["--tmpfs", "/tmp:rw,exec,size=64m,mode=1777"],
        ["--sysctl", "net.ipv4.ip_unprivileged_port_start=0"],
    ):
        assert any(cmd[i : i + len(pair)] == pair for i in range(len(cmd))), pair
    assert "--rm" in cmd
    assert "--runtime" not in cmd  # runc fallback: no runsc flag

    runsc_cmd = build_command("bd-det-job-1", "C:/w", "runsc", WALL_CLOCK_S, "detonate")
    assert runsc_cmd[runsc_cmd.index("--runtime") + 1] == "runsc"


def test_fallback_note_says_runsc_is_unavailable() -> None:
    fallback = _note("runc")
    assert "FALLBACK" in fallback and "runsc unavailable" in fallback
    assert "network=none" in fallback and "512m" in fallback and "pids=128" in fallback
    assert "FALLBACK" not in _note("runsc")


@pytest.mark.parametrize(
    ("tool", "expected"),
    ((ToolName.detonate, "detonate"), (ToolName.custom_script, "custom_script")),
)
def test_twin_tool_dispatch_routes_sandboxed_tools(monkeypatch, tool, expected) -> None:
    """The twin's production entrypoint calls tools.execute, so both F7
    tools must reach the sandbox through that dispatcher."""
    seen = {}

    def fake(call, mount, wall_s):
        seen.update(call=call, mount=mount, wall_s=wall_s)
        return expected

    target = "detonate" if tool == ToolName.detonate else "run_custom_script"
    monkeypatch.setattr(f"bd_forensics.sandbox.{target}", fake)
    args = {"path": "/sample"} if tool == ToolName.detonate else {"code": "pass"}
    call = ToolCall(job_id="job-1", case_id="case-1", tool=tool, args=args)

    assert tools.execute(call, "/mnt/disk", timeout_s=12.5) == expected
    assert seen == {"call": call, "mount": "/mnt/disk", "wall_s": 12.5}


def _load_runner(tmp_path):
    path = tmp_path / "runner.py"
    path.write_text(RUNNER_CODE, encoding="utf-8")
    spec = importlib.util.spec_from_file_location("bd_runner_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _free_port() -> int:
    probe = socket.socket()
    probe.bind(("127.0.0.1", 0))
    port = probe.getsockname()[1]
    probe.close()
    return port


def _dns_query(name: str) -> bytes:
    qname = b"".join(bytes([len(part)]) + part.encode() for part in name.split(".")) + b"\x00"
    header = struct.pack(">HHHHHH", 0xB00D, 0x0100, 1, 0, 0, 0)
    return header + qname + struct.pack(">HH", 1, 1)


def test_runner_resolver_sinkholes_and_logs(tmp_path) -> None:
    """The resolver itself, no docker: a query for the fake C2 domain is
    answered with the sinkhole A record and the name is logged (that log is
    how the beacon is caught)."""
    module = _load_runner(tmp_path)
    port = _free_port()
    threading.Thread(target=module._resolver, args=(port,), daemon=True).start()

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(5.0)
    data = b""
    for _ in range(20):  # tiny race: the thread may not be bound yet
        try:
            sock.sendto(_dns_query("c2.bodydouble-demo.test"), ("127.0.0.1", port))
            data, _ = sock.recvfrom(512)
            break
        except (socket.timeout, OSError):
            continue
    assert data, "resolver did not answer"
    assert struct.unpack(">H", data[2:4])[0] & 0x8000  # QR set: it is a response
    assert data[-4:] == b"\x00\x00\x00\x00"  # A record: the sinkhole IP
    assert "c2.bodydouble-demo.test" in module.dns_log


def test_detonate_refuses_symlink_escape_before_starting_docker(tmp_path) -> None:
    tree = tmp_path / "tree"
    tree.mkdir()
    outside = tmp_path / "outside.sh"
    outside.write_text("#!/bin/sh\necho escaped\n")
    try:
        (tree / "sample").symlink_to(outside)
    except OSError as exc:
        pytest.skip(f"symlinks unavailable: {exc}")
    call = ToolCall(
        job_id="job-escape", case_id="case-1", tool=ToolName.detonate,
        args={"path": "sample"},
    )

    result = detonate(call, str(tree), docker="definitely-not-installed")

    assert result.exit_code == 2
    assert "escapes the mounted disk" in result.stderr


# ----------------------------------------------------------------- docker-gated


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not reachable")
def test_detonate_captures_c2_lookup_and_miner_write() -> None:
    """Done when: DNS lookups and file writes captured -- the C2 lookup
    from the planted script appears -- and the container is destroyed."""
    call = ToolCall(
        job_id=f"job-{uuid.uuid4().hex[:6]}", case_id="case-1",
        tool=ToolName.detonate, args={"path": "/usr/local/bin/.bdrv"},
    )
    result = detonate(call, str(VICTIM))

    note = result.stdout.splitlines()[0]
    if detect_runtime() == "runc":
        assert "FALLBACK" in note  # the result says so
    else:
        assert "runsc" in note

    assert "c2.bodydouble-demo.test" in result.dns_queries, result.stdout
    assert "/tmp/.bd-miner" in result.file_writes
    miner = next(a for a in result.artifacts if a.path == "/tmp/.bd-miner")
    assert miner.sha256 == hashlib.sha256(b"bd-demo-miner-stand-in\n").hexdigest()
    assert result.exit_code == 0, result.stderr
    assert result.containers_left == 0
    assert result.packets_out == 0


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not reachable")
def test_detonate_kills_runaway_at_the_limits(tmp_path) -> None:
    """A fork-bomb stand-in is killed at the wall-clock limit and the
    container is destroyed (PRD resource limits: 1 vCPU / 512 MB / 60 s /
    128 PIDs / read-only rootfs / tmpfs scratch)."""
    tree = tmp_path / "tree"
    (tree / "usr/local/bin").mkdir(parents=True)
    # POSIX sh (dash) rejects ':' as a function name, and a background-only
    # bomb lets the direct child exit before the wall clock fires -- so use
    # a named function and hold the foreground until the limit kills it.
    # newline="": a CRLF shebang would not exec inside the Linux container
    (tree / "usr/local/bin/forkbomb").write_text(
        "#!/bin/sh\nf(){ f|f& }\nf\nsleep 999\n", newline="\n"
    )
    call = ToolCall(
        job_id=f"job-{uuid.uuid4().hex[:6]}", case_id="case-1",
        tool=ToolName.detonate, args={"path": "usr/local/bin/forkbomb"},
    )
    result = detonate(call, str(tree), wall_s=5.0)
    assert result.exit_code == 124
    assert "wall-clock" in result.stdout  # killed at the limit, not exited
    assert result.containers_left == 0


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not reachable")
def test_custom_script_sees_mount_read_only(tmp_path) -> None:
    """Pattern A: planner Python runs in a no-network container with the
    mount read-only; writes land in the scratch and are captured."""
    code = (
        "import os, pathlib\n"
        "mount = pathlib.Path('/mnt')\n"
        "print(sorted(p.name for p in mount.iterdir()))\n"
        "try:\n"
        "    (mount / 'attack.txt').write_text('pwned')\n"
        "    print('WROTE')\n"
        "except OSError as exc:\n"
        "    print('refused', exc.errno)\n"
        "open('/tmp/bd-note.txt', 'w').write('scratch write ok')\n"
        "print('hostname', os.uname().nodename)\n"
    )
    call = ToolCall(
        job_id=f"job-{uuid.uuid4().hex[:6]}", case_id="case-1",
        tool=ToolName.custom_script, args={"code": code},
    )
    result = run_custom_script(call, str(VICTIM))
    assert result.exit_code == 0, result.stdout + result.stderr
    assert "etc" in result.stdout  # the mounted disk is visible
    assert "WROTE" not in result.stdout  # ...and read-only
    assert "refused" in result.stdout
    assert "/tmp/bd-note.txt" in result.file_writes  # scratch writes captured
    assert result.containers_left == 0
    assert result.packets_out == 0
