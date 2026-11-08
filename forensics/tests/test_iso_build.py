"""ISO bootstrap trust boundary, egress, build, and secret hygiene."""
from __future__ import annotations

import base64
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import shutil
import subprocess
import threading

import pytest

from bd_forensics.metadata import configure_boot, fetch_bootstrap

REPO = Path(__file__).resolve().parents[2]
NFT_TEMPLATE = REPO / "iso/rootfs/etc/bd/egress.nft"


@contextmanager
def metadata_server(payload):
    body = base64.b64encode(json.dumps(payload).encode())

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            assert self.path == "/v1/user-data"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1/user-data"
    finally:
        server.shutdown()


def valid_payload(**changes):
    payload = {
        "case_id": "case-123", "token": "one-time-token",
        "control_plane": "http://10.20.0.2:8000",
        "vpc_subnet": "10.20.0.0/24", "vpc_ip": "10.20.0.20",
    }
    payload.update(changes)
    return payload


def test_valid_user_data_renders_expected_accept_line(tmp_path) -> None:
    with metadata_server(valid_payload()) as url:
        got = fetch_bootstrap(url)
        nft, bootstrap = tmp_path / "egress.nft", tmp_path / "bootstrap.json"
        configure_boot(url, NFT_TEMPLATE, nft, bootstrap)
    assert got == valid_payload()
    assert "ip daddr 10.20.0.0/24 accept" in nft.read_text()
    assert json.loads(bootstrap.read_text()) == valid_payload()


@pytest.mark.parametrize("change", [
    {"vpc_subnet": "10.0.0.0/8;reboot", "vpc_ip": "10.20.0.20"},
    {"vpc_ip": "192.0.2.10"},
    {"control_plane": "http://203.0.113.10:8000"},
    {"token": "bad;reboot"},
])
def test_invalid_user_data_fails_closed(change, tmp_path) -> None:
    nft, bootstrap = tmp_path / "egress.nft", tmp_path / "bootstrap.json"
    with metadata_server(valid_payload(**change)) as url:
        with pytest.raises(ValueError):
            configure_boot(url, NFT_TEMPLATE, nft, bootstrap)
    rules = nft.read_text()
    assert "policy drop" in rules
    assert "ip daddr" not in rules
    assert not bootstrap.exists()


def test_planted_block_device_config_has_no_effect(tmp_path) -> None:
    victim = tmp_path / "victim"
    victim.mkdir()
    (victim / "bd-deploy.env").write_text("BD_SUBNET=0.0.0.0/0; reboot\n")
    with metadata_server(valid_payload()) as url:
        nft, bootstrap = tmp_path / "egress.nft", tmp_path / "bootstrap.json"
        configure_boot(url, NFT_TEMPLATE, nft, bootstrap)
    assert "10.20.0.0/24" in nft.read_text()
    init = (REPO / "iso/boot/init").read_text()
    boot = (REPO / "iso/rootfs/etc/bd/boot.sh").read_text()
    assert "bd-deploy.env" not in init
    assert "deploy.env" not in boot
    assert "source " not in boot and ". $" not in boot
    assert "ro,noexec,nosuid,nodev" in boot


@pytest.mark.skipif(not shutil.which("docker"), reason="docker unavailable")
def test_alpine_stage_contains_default_drop_runsc_and_no_keys(tmp_path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    subprocess.run([
        "docker", "run", "--rm", "-v", f"{REPO.as_posix()}:/src:ro",
        "-v", f"{out.as_posix()}:/out", "alpine:3.20",
        "sh", "/src/iso/build.sh", "--stage",
    ], check=True, timeout=180)
    stage = out / "stage"
    assert "policy drop" in (stage / "etc/bd/egress.nft").read_text()
    daemon = json.loads((stage / "etc/docker/daemon.json").read_text())
    assert daemon["runtimes"]["runsc"]["path"] == "/usr/bin/runsc"
    image_text = "\n".join(
        p.read_text(errors="ignore") for p in stage.rglob("*") if p.is_file()
    ).casefold()
    assert "vultr_api_key=" not in image_text
    assert "inference_api_key=" not in image_text
