"""S4: create shop-prod, plant the demo indicators, prove they survive a reboot,
snapshot it. shop-prod itself is always deleted in `finally`; the snapshot
(description "body-double shop-prod planted") is the deliverable and the sweep
removes it later.

    uv run python scripts/s4_shop_prod.py

SSH access goes to a `ubuntu` sudo user via cloud-init, NOT root: plant.sh
refuses to run when /root/.ssh/authorized_keys already exists, and the planted
rogue root key must be the only one there.
Evidence: evals/results/real-mode/S4/ (API responses, indicator hashes, timings).
"""
from __future__ import annotations

import base64
import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bdvultr import REPO, Api, evidence, load_secrets  # noqa: E402

REGION, PLAN, UBUNTU_2404 = "ewr", "vc2-1c-1gb", 2284
SSH_KEY = Path.home() / ".ssh" / "bd_vultr"
INDICATORS = ["etc/cron.d/bdrv", "root/.ssh/authorized_keys", "usr/bin/top",
              "usr/local/bin/.bdrv", "var/backups/notes-to-ai.txt"]
OUT = evidence("S4")


def ssh_opts() -> list[str]:
    return ["-i", str(SSH_KEY), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null",
            "-o", "LogLevel=ERROR", "-o", "ConnectTimeout=10", "-o", "BatchMode=yes"]


def ssh(ip: str, cmd: str, check: bool = True) -> str:
    p = subprocess.run(["ssh", *ssh_opts(), f"ubuntu@{ip}", cmd], capture_output=True, text=True, timeout=300)
    if check and p.returncode != 0:
        raise RuntimeError(f"ssh `{cmd}` -> {p.returncode}: {p.stderr.strip()}")
    return p.stdout


def wait_ssh(ip: str, timeout_s: float = 600) -> None:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        p = subprocess.run(["ssh", *ssh_opts(), f"ubuntu@{ip}", "cloud-init status --wait >/dev/null; echo up"],
                           capture_output=True, text=True, timeout=400)
        if p.stdout.strip().endswith("up"):
            return
        time.sleep(10)
    raise TimeoutError(f"ssh to {ip} not up after {timeout_s}s")


def indicator_hashes(ip: str) -> dict[str, str]:
    out = ssh(ip, "sudo sha256sum " + " ".join("/" + p for p in INDICATORS))
    return {line.split()[1].lstrip("/"): line.split()[0] for line in out.splitlines()}


def main() -> int:
    env = load_secrets()
    api = Api(env["VULTR_API_KEY"], evidence_dir=OUT)
    pub = subprocess.run(["ssh-keygen", "-y", "-f", str(SSH_KEY)], capture_output=True,
                         text=True, check=True).stdout.strip()
    cloud_config = (
        "#cloud-config\nusers:\n  - name: ubuntu\n    groups: sudo\n    shell: /bin/bash\n"
        '    sudo: "ALL=(ALL) NOPASSWD:ALL"\n'
        f"    ssh_authorized_keys:\n      - {pub}\n")
    expected = {p: hashlib.sha256((REPO / "demo/victim" / p).read_bytes()).hexdigest() for p in INDICATORS}
    timings: dict[str, float] = {}
    inst_id = None
    try:
        _, data = api.call("POST", "/v2/instances", {
            "region": REGION, "plan": PLAN, "os_id": UBUNTU_2404, "label": "shop-prod",
            "hostname": "shop-prod", "tags": ["body-double"], "backups": "disabled",
            "user_data": base64.b64encode(cloud_config.encode()).decode()}, name="create-shop-prod")
        inst_id = data["instance"]["id"]
        inst, timings["create_to_active_s"] = api.wait(f"/v2/instances/{inst_id}", "instance",
                                                       "status", "active", 900, 10)
        ip = inst["main_ip"]
        print(f"shop-prod {inst_id} active at {ip}")
        wait_ssh(ip)

        # Real-mode finding: Vultr's Ubuntu 24.04 cloud-init creates
        # /root/.ssh/authorized_keys even with no sshkey_ids. If it holds nothing
        # but our own ubuntu key (any options prefix) or nothing at all, it is a
        # cloud-init artifact of this throwaway box: record and remove it so
        # plant.sh's guard passes. Anything else aborts.
        pre = ssh(ip, "sudo test -e /root/.ssh/authorized_keys && sudo cat /root/.ssh/authorized_keys || echo ABSENT")
        key_b64 = pub.split()[1]
        lines = [l for l in pre.splitlines() if l.strip() and not l.startswith("#")]
        foreign = [l for l in lines if key_b64 not in l and l.strip() != "ABSENT"]
        summary = {"existed": pre.strip() != "ABSENT", "key_lines": len(lines),
                   "only_our_cloud_init_key": not foreign,
                   "options_prefixes": sorted({l.split(" ssh-")[0] for l in lines if " ssh-" in l})}
        (OUT / "root-authorized-keys-before-plant.json").write_text(json.dumps(summary, indent=2))
        print("root authorized_keys before plant:", summary)
        if foreign:
            raise RuntimeError("root authorized_keys holds a key we did not put there; not planting")
        if summary["existed"]:
            ssh(ip, "sudo rm -f /root/.ssh/authorized_keys")

        subprocess.run(["scp", *ssh_opts(), "-r", "-q", str(REPO / "demo/victim"), str(REPO / "demo/plant.sh"),
                        f"ubuntu@{ip}:/tmp/"], check=True, timeout=300)
        plant_out = ssh(ip, "sudo env BD_PLANT_DEMO=1 sh /tmp/plant.sh /tmp/victim && rm -rf /tmp/victim /tmp/plant.sh")
        before = indicator_hashes(ip)

        # guest-initiated, clean reboot (first attempt used the API reboot and the
        # box never answered SSH again within 10 min; see run notes in findings)
        t_reboot = time.monotonic()
        ssh(ip, "sudo sync; (sleep 2; sudo systemctl reboot) >/dev/null 2>&1 &", check=False)
        time.sleep(45)
        try:
            wait_ssh(ip, 900)
        except TimeoutError:
            api.call("GET", f"/v2/instances/{inst_id}", name="state-at-reboot-timeout")
            raise
        timings["reboot_to_ssh_s"] = time.monotonic() - t_reboot
        after = indicator_hashes(ip)
        uptime = ssh(ip, "uptime -s; systemctl is-active cron; ls -la /etc/cron.d/bdrv").strip()

        report = {"instance_id": inst_id, "plant_stdout": plant_out.strip(),
                  "expected_sha256": expected, "before_reboot": before, "after_reboot": after,
                  "after_reboot_uptime_cron": uptime,
                  "survived_reboot": before == after == expected}
        (OUT / "indicators.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({k: report[k] for k in ("plant_stdout", "survived_reboot")}))
        if not report["survived_reboot"]:
            raise RuntimeError("indicators changed across reboot")

        t0 = time.monotonic()
        _, snap = api.call("POST", "/v2/snapshots", {"instance_id": inst_id,
                                                     "description": "body-double shop-prod planted"},
                           name="create-snapshot")
        snap_id = snap["snapshot"]["id"]
        final, _ = api.wait(f"/v2/snapshots/{snap_id}", "snapshot", "status", "complete", 3600, 20)
        timings["snapshot_create_to_complete_s"] = time.monotonic() - t0
        api.call("GET", f"/v2/snapshots/{snap_id}", name="snapshot-complete")
        print(f"snapshot {snap_id} complete in {timings['snapshot_create_to_complete_s']:.0f}s "
              f"(size {final.get('size')}, compressed {final.get('compressed_size')})")
        (OUT / "result.json").write_text(json.dumps({"snapshot_id": snap_id, "timings_s": timings}, indent=2))
        return 0
    finally:
        if inst_id:
            api.call("DELETE", f"/v2/instances/{inst_id}", name="delete-shop-prod", ok=(404,))
            print(f"deleted shop-prod {inst_id}")
        (OUT / "timings.json").write_text(json.dumps(timings, indent=2))


if __name__ == "__main__":
    sys.exit(main())
