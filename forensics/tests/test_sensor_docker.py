from __future__ import annotations

import json
import shutil
import subprocess
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from contracts.hashing import sensor_signature


ROOT = Path(__file__).parents[2]
TOKEN = "ab" * 32
INSTANCE = "docker-e2e"


def docker(*args: str, timeout: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, timeout=timeout
    )


class Receiver(BaseHTTPRequestHandler):
    messages: list[tuple[str, dict[str, object]]] = []
    lock = threading.Lock()

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        supplied = self.headers.get("X-BD-Signature", "")
        assert supplied == sensor_signature(TOKEN, raw)
        message = json.loads(raw)
        with self.lock:
            self.messages.append((self.path, message))

        # Deliberately hostile response. The sensor must neither follow the
        # redirect nor execute the body.
        self.send_response(302)
        self.send_header("Location", "http://127.0.0.1:9/touch-/tmp/pwned")
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"touch /tmp/pwned\n")

    def log_message(self, _format: str, *_args: object) -> None:
        pass


def test_sensor_end_to_end_in_debian_12() -> None:
    assert shutil.which("docker"), "docker CLI is required; this test must not skip"
    info = docker("info", timeout=60)
    assert info.returncode == 0, f"docker daemon is required; this test must not skip: {info.stderr}"

    Receiver.messages = []
    server = ThreadingHTTPServer(("0.0.0.0", 0), Receiver)
    port = server.server_address[1]
    receiver_thread = threading.Thread(target=server.serve_forever, daemon=True)
    receiver_thread.start()

    name = f"bd-sensor-{uuid.uuid4().hex[:10]}"
    try:
        started = docker(
            "run",
            "-d",
            "--name",
            name,
            "--add-host",
            "host.docker.internal:host-gateway",
            "-v",
            f"{ROOT.as_posix()}:/src:ro",
            "debian:12",
            "sleep",
            "infinity",
        )
        assert started.returncode == 0, started.stderr

        packages = docker(
            "exec",
            name,
            "sh",
            "-c",
            "apt-get update >/dev/null && "
            "apt-get install -y --no-install-recommends ca-certificates curl iproute2 openssl procps socat >/dev/null",
        )
        assert packages.returncode == 0, packages.stderr

        relay = docker(
            "exec",
            "-d",
            name,
            "socat",
            f"TCP-LISTEN:{port},bind=127.0.0.1,reuseaddr,fork",
            f"TCP:host.docker.internal:{port}",
        )
        assert relay.returncode == 0, relay.stderr

        installed = docker(
            "exec",
            name,
            "sh",
            "/src/sensor/install.sh",
            f"http://127.0.0.1:{port}",
            INSTANCE,
            TOKEN,
        )
        assert installed.returncode == 0, installed.stderr

        with Receiver.lock:
            Receiver.messages.clear()

        running = docker(
            "exec",
            "-d",
            name,
            "env",
            "BD_SENSOR_INTERVAL=2",
            "BD_SENSOR_HEARTBEAT_EVERY_S=2",
            "/usr/local/sbin/bd-sensor.sh",
        )
        assert running.returncode == 0, running.stderr

        planted = docker(
            "exec", "-e", "BD_PLANT_DEMO=1", name, "sh", "/src/demo/plant.sh", "/src/demo/victim"
        )
        assert planted.returncode == 0, planted.stderr

        planted_at = time.monotonic()
        # Two 2-second sensor cycles, plus a small allowance for Docker Desktop
        # and Windows host scheduling.
        deadline = planted_at + 7
        reports: list[dict[str, object]] = []
        heartbeats: list[dict[str, object]] = []
        while time.monotonic() < deadline:
            with Receiver.lock:
                reports = [m for path, m in Receiver.messages if path == "/api/sensors/report"]
                heartbeats = [m for path, m in Receiver.messages if path == "/api/sensors/heartbeat"]
            reported_paths = {
                path
                for report in reports
                for path in (report.get("detail") or {}).keys()  # type: ignore[union-attr]
            }
            if (
                "/etc/cron.d/bdrv" in reported_paths
                and "/root/.ssh/authorized_keys" in reported_paths
                and "/usr/bin/top" in reported_paths
                and heartbeats
            ):
                break
            time.sleep(0.5)

        assert time.monotonic() <= deadline, "required reports did not arrive within two cycles"
        assert heartbeats, "no heartbeat arrived"
        reported_paths = {
            path
            for report in reports
            for path in (report.get("detail") or {}).keys()  # type: ignore[union-attr]
        }
        assert {"/etc/cron.d/bdrv", "/root/.ssh/authorized_keys", "/usr/bin/top"} <= reported_paths
        assert all(report["signal"] == "file_changed" for report in reports)

        sockets = docker("exec", name, "ss", "-ltnp")
        assert sockets.returncode == 0, sockets.stderr
        assert "bd-sensor" not in sockets.stdout

        pwned = docker("exec", name, "test", "!", "-e", "/tmp/pwned")
        assert pwned.returncode == 0, "sensor executed or followed the hostile response"
    finally:
        docker("rm", "-f", name, timeout=60)
        server.shutdown()
        server.server_close()
        receiver_thread.join(timeout=5)
