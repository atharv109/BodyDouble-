"""Forensics ISO build, egress, metadata bootstrap, and secret hygiene."""
from __future__ import annotations

import base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import threading

import pytest

from bd_forensics.metadata import fetch_bootstrap, write_agent_env

REPO = Path(__file__).resolve().parents[2]


def test_metadata_bootstrap_uses_base64_json_from_fake_server(tmp_path) -> None:
    expected = {
        "case_id": "case-123", "token": "one-time;$(not-executed)",
        "control_plane": "http://10.0.0.2:8000",
    }
    body = base64.b64encode(json.dumps(expected).encode())

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/v1/user-data"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        got = fetch_bootstrap(f"http://127.0.0.1:{server.server_port}/v1/user-data")
    finally:
        server.shutdown()
    assert got == expected
    env = tmp_path / "agent.env"
    write_agent_env(env, got)
    text = env.read_text()
    assert "BD_CASE_ID=case-123" in text
    assert "'one-time;$(not-executed)'" in text


@pytest.mark.skipif(not shutil.which("docker"), reason="docker unavailable")
def test_alpine_stage_contains_default_drop_runsc_and_no_keys(tmp_path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    mount = REPO.as_posix()
    subprocess.run([
        "docker", "run", "--rm", "-v", f"{mount}:/src:ro",
        "-v", f"{out.as_posix()}:/out", "alpine:3.20",
        "sh", "/src/iso/build.sh", "--stage",
    ], check=True, timeout=180)
    stage = out / "stage"
    egress = (stage / "etc/bd/egress.nft").read_text()
    assert "policy drop" in egress
    assert "ip daddr __BD_VPC_SUBNET__ accept" in egress
    daemon = json.loads((stage / "etc/docker/daemon.json").read_text())
    assert daemon["runtimes"]["runsc"]["path"] == "/usr/bin/runsc"
    boot = (stage / "etc/bd/boot.sh").read_text()
    assert "169.254.169.254/v1/user-data" in boot
    image_text = "\n".join(
        p.read_text(errors="ignore") for p in stage.rglob("*") if p.is_file()
    ).casefold()
    assert "vultr_api_key=" not in image_text
    assert "inference_api_key=" not in image_text
    assert "placeholder-one-time-token" not in image_text
