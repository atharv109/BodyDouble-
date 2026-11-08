"""Detonation sandbox (F7): detonate runs ONE extracted file, and
custom_script runs the planner's Python, inside a no-network container on
the twin -- gVisor (runsc) when that runtime is registered with docker,
otherwise plain Docker with --network none, no capabilities and the default
seccomp profile, and the ToolResult says which.

A sinkhole resolver inside the container namespace answers every DNS lookup
with the sinkhole IP and logs the queried name -- that log is how the
beacon is caught. Limits per PRD: 1 vCPU, 512 MB, 60 s wall clock, 128
PIDs, read-only rootfs, tmpfs scratch. The container is removed after every
run, and the ToolResult reports containers_left / packets_out (F16): both
must be 0 -- with --network none no packet can leave the twin.
"""
from __future__ import annotations

import json
import shlex
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from contracts.models import Artifact, ToolCall, ToolName, ToolResult

from .tools import valid_args

IMAGE = "python:3.12-slim"  # debian slim: has glibc getent AND python3
WALL_CLOCK_S = 60.0
CONTAINER_LIMITS = "network=none cpus=1 memory=512m pids=128 read-only-rootfs tmpfs-scratch"
RESULT_BEGIN = "==BD-SANDBOX-RESULT=="
RESULT_END = "==BD-SANDBOX-RESULT-END=="

# The in-container harness. It runs as the container's entrypoint (PID 1):
# starts the sinkhole resolver on loopback, runs the target in a new session
# with a wall-clock cap, diffs the tmpfs scratch for file writes, and
# reports one JSON block. The target's stdout/stderr are serialized INTO
# that JSON, so a target that prints the markers can never forge a result.
RUNNER_CODE = '''\
# In-container detonation harness (bd_forensics.sandbox). argv: mode wall cmd...
import hashlib
import json
import os
import shutil
import signal
import socket
import struct
import subprocess
import sys
import threading

SINKHOLE_IP = "0.0.0.0"
RESULT_BEGIN = "==BD-SANDBOX-RESULT=="
RESULT_END = "==BD-SANDBOX-RESULT-END=="

dns_log = []
dns_lock = threading.Lock()
resolver_ready = threading.Event()


def _question(data):
    # returns (queried name, the raw question-section bytes)
    i = 12
    labels = []
    while True:
        length = data[i]
        if length == 0:
            i += 1
            break
        labels.append(data[i + 1 : i + 1 + length].decode("ascii", "replace"))
        i += 1 + length
    i += 4  # QTYPE + QCLASS
    return ".".join(labels), data[12:i]


def _answer(data, question_bytes):
    # echo the ID, QR/AA/RA set, one A record pointing at the sinkhole
    header = data[:2] + bytes([0x85, 0x80]) + struct.pack(">HHHH", 1, 1, 0, 0)
    record = bytes((0xC0, 0x0C)) + struct.pack(">HHIH", 1, 1, 60, 4)
    record += socket.inet_aton(SINKHOLE_IP)
    return header + question_bytes + record


def _resolver(port):
    srv = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        srv.bind(("127.0.0.1", port))
    except OSError as exc:
        with dns_lock:
            dns_log.append("resolver-error: " + str(exc))
        resolver_ready.set()
        return
    resolver_ready.set()
    while True:
        try:
            data, addr = srv.recvfrom(512)
        except OSError:
            return
        try:
            name, question_bytes = _question(data)
        except Exception:
            name, question_bytes = "<unparseable>", data[12:]
        with dns_lock:
            dns_log.append(name)
        srv.sendto(_answer(data, question_bytes), addr)


def _writes(before):
    writes = []
    for name in sorted(set(os.listdir("/tmp")) - before):
        path = os.path.join("/tmp", name)
        if not os.path.isfile(path):
            continue
        with open(path, "rb") as fh:
            blob = fh.read()
        writes.append({
            "path": "/tmp/" + name,
            "sha256": hashlib.sha256(blob).hexdigest(),
            "excerpt": blob[:2000].decode("utf-8", "replace"),
        })
    return writes


def main():
    mode, wall = sys.argv[1], float(sys.argv[2])
    cmd = sys.argv[3:]
    port = int(os.environ.get("BD_RESOLVER_PORT", "53"))
    threading.Thread(target=_resolver, args=(port,), daemon=True).start()
    if not resolver_ready.wait(timeout=5):
        raise RuntimeError("sinkhole resolver did not start")

    if mode == "detonate":
        shutil.copyfile("/work/target", "/tmp/bd-target")
        os.chmod("/tmp/bd-target", 0o755)
        cmd = ["/tmp/bd-target"]
    before = set(os.listdir("/tmp"))
    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, start_new_session=True
    )
    timed_out = False
    try:
        out, err = proc.communicate(timeout=wall)
    except subprocess.TimeoutExpired:
        timed_out = True
        # kill the whole process group: no orphan may hold the pipes open
        os.killpg(proc.pid, signal.SIGKILL)
        out, err = proc.communicate()
    print(RESULT_BEGIN)
    print(json.dumps({
        "exit": 124 if timed_out else proc.returncode,
        "timed_out": timed_out,
        "dns": list(dns_log),
        "writes": _writes(before),
        "stdout": (out or b"").decode("utf-8", "replace"),
        "stderr": (err or b"").decode("utf-8", "replace"),
    }))
    print(RESULT_END)


try:
    main()
except Exception as exc:
    print(RESULT_BEGIN)
    print(json.dumps({"exit": 2, "timed_out": False, "dns": [], "writes": [],
                      "stdout": "", "stderr": "harness error: " + str(exc)}))
    print(RESULT_END)
'''

_runtime: str | None = None


def detect_runtime(docker: str = "docker") -> str:
    """runsc when gVisor is registered with docker; otherwise the docker
    fallback the PRD allows (and the ToolResult must say so)."""
    global _runtime
    if _runtime is None:
        proc = subprocess.run(
            [docker, "info", "--format", "{{json .Runtimes}}"],
            capture_output=True, text=True, timeout=60,
        )
        if proc.returncode != 0:
            raise RuntimeError("docker not reachable: " + proc.stderr.strip())
        runtimes = json.loads(proc.stdout or "{}")
        _runtime = "runsc" if "runsc" in runtimes else "runc"
    return _runtime


def _note(runtime: str) -> str:
    if runtime == "runsc":
        return f"[sandbox] runtime=runsc (gVisor) {CONTAINER_LIMITS}"
    return (
        f"[sandbox] runtime=runc FALLBACK (runsc unavailable): docker "
        f"--network none, cap-drop ALL, default seccomp {CONTAINER_LIMITS}"
    )


def build_command(
    name: str,
    work_dir: str,
    runtime: str,
    wall_s: float,
    mode: str,
    extra_binds: list[str] | None = None,
) -> list[str]:
    """The exact docker command a detonate/custom_script step runs."""
    cmd = [
        "docker", "run", "--rm", "--name", name,
        "--network", "none", "--dns", "127.0.0.1",
        "--cpus", "1", "--memory", "512m", "--pids-limit", "128",
        "--read-only", "--tmpfs", "/tmp:rw,exec,size=64m,mode=1777",
        "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
        # lets the cap-dropped resolver bind :53 without any capability
        "--sysctl", "net.ipv4.ip_unprivileged_port_start=0",
    ]
    if runtime == "runsc":
        cmd += ["--runtime", "runsc"]
    cmd += ["-v", f"{work_dir}:/work:ro"]
    cmd += list(extra_binds or [])
    args = ["/work/runner.py", mode, str(wall_s)]
    if mode == "script":
        args += ["python3", "/work/script.py", "/mnt"]
    cmd += ["--entrypoint", "python3", IMAGE, *args]
    return cmd


def containers_left(name: str, docker: str = "docker") -> int:
    """How many detonation containers with this name (or name prefix, for
    the F16 sweep) still exist after cleanup -- must be 0."""
    proc = subprocess.run(
        [docker, "ps", "-a", "--filter", f"name={name}", "-q"],
        capture_output=True, text=True, timeout=60,
    )
    return len([line for line in proc.stdout.split() if line])


def _ensure_image(docker: str = "docker") -> None:
    proc = subprocess.run([docker, "image", "inspect", IMAGE], capture_output=True)
    if proc.returncode != 0:
        subprocess.run([docker, "pull", IMAGE], capture_output=True, timeout=600)


def _refused(call: ToolCall, why: str) -> ToolResult:
    return ToolResult(
        job_id=call.job_id, code="# refused: " + why, stdout="",
        stderr="refused: " + why, exit_code=2, duration_ms=0,
        containers_left=0, packets_out=0,
    )


def _parse(proc, runtime, code, duration_ms, call, name, docker) -> ToolResult:
    stdout = proc.stdout or ""
    left = containers_left(name, docker)
    if RESULT_BEGIN in stdout and RESULT_END in stdout:
        blob = stdout.split(RESULT_BEGIN, 1)[1].split(RESULT_END, 1)[0].strip()
        payload = json.loads(blob)
        note = _note(runtime)
        if payload.get("timed_out"):
            note += " [killed at wall-clock limit]"
        writes = payload.get("writes", [])
        return ToolResult(
            job_id=call.job_id,
            code=code,
            stdout=note + "\n" + payload.get("stdout", ""),
            stderr=payload.get("stderr", ""),
            exit_code=int(payload.get("exit", proc.returncode)),
            duration_ms=duration_ms,
            artifacts=[
                Artifact(path=w["path"], sha256=w["sha256"], excerpt=w.get("excerpt", ""))
                for w in writes
            ],
            dns_queries=list(payload.get("dns", [])),
            file_writes=[w["path"] for w in writes],
            containers_left=left,
            packets_out=0,  # --network none: nothing can leave the twin
        )
    # the harness itself died (OOM kill, crash): docker's exit code is the truth
    return ToolResult(
        job_id=call.job_id, code=code, stdout=_note(runtime) + "\n" + stdout,
        stderr=proc.stderr, exit_code=proc.returncode, duration_ms=duration_ms,
        containers_left=left, packets_out=0,
    )


def _run_sandbox(call: ToolCall, mount: str, mode: str, wall_s: float, docker: str) -> ToolResult:
    if not valid_args(call.tool, call.args):
        return _refused(call, f"invalid args for {call.tool}: {call.args}")
    name = f"bd-det-{call.job_id}"
    work = Path(tempfile.mkdtemp(prefix="bd-sandbox-"))
    try:
        (work / "runner.py").write_text(RUNNER_CODE, encoding="utf-8")
        extra_binds: list[str] = []
        if mode == "detonate":
            try:
                mount_root = Path(mount).resolve()
                source = (mount_root / str(call.args["path"]).strip().strip("/")).resolve()
                if source == mount_root or mount_root not in source.parents:
                    return _refused(call, "extracted path escapes the mounted disk")
                if not source.is_file():
                    return _refused(call, "extracted path is not a regular file")
                shutil.copyfile(source, work / "target")
            except OSError as exc:
                return _refused(call, f"cannot extract {call.args['path']}: {exc}")
        else:
            (work / "script.py").write_text(str(call.args["code"]), encoding="utf-8")
            extra_binds = ["-v", f"{Path(mount).resolve().as_posix()}:/mnt:ro"]
        runtime = detect_runtime(docker)
        _ensure_image(docker)
        cmd = build_command(name, work.as_posix(), runtime, wall_s, mode, extra_binds)
        code = shlex.join(cmd)
        t0 = time.monotonic()
        try:
            proc = subprocess.run(
                cmd, capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=wall_s + 60,
            )
        except subprocess.TimeoutExpired:
            subprocess.run([docker, "rm", "-f", name], capture_output=True, timeout=60)
            return ToolResult(
                job_id=call.job_id, code=code, stdout="", stderr="step timed out",
                exit_code=124, duration_ms=int((time.monotonic() - t0) * 1000),
                containers_left=containers_left(name, docker), packets_out=0,
            )
        duration_ms = int((time.monotonic() - t0) * 1000)
        return _parse(proc, runtime, code, duration_ms, call, name, docker)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def detonate(
    call: ToolCall, mount: str, wall_s: float = WALL_CLOCK_S, docker: str = "docker"
) -> ToolResult:
    """Run one extracted file in the no-network detonation container."""
    return _run_sandbox(call, mount, "detonate", wall_s, docker)


def run_custom_script(
    call: ToolCall, mount: str, wall_s: float = WALL_CLOCK_S, docker: str = "docker"
) -> ToolResult:
    """Run the planner's Python in a no-network container with the mount
    read-only (PRD Pattern A)."""
    return _run_sandbox(call, mount, "script", wall_s, docker)
