"""S5: day-one tests T1-T4 against real Vultr, one run, cleaned up in `finally`.

    uv run python scripts/s5_twin.py [--checkpoint-dir DIR] [--checkpoint-wait 900]

Creates (all tagged body-double / described bd-*):
  bd-vpc       the shared investigation VPC; reused from BD_VPC_ID if alive,
               else created and saved to BD_VPC_ID/BD_VPC_SUBNET (kept, $0/hr)
  bd-twin-fw   firewall group with no accept rules = inbound deny (deleted)
  bd-cp        Ubuntu VM in the VPC running scripts/cp_stub.py (deleted)
  bd-twin-t1a  T1: ONE create call with snapshot_id AND iso_id (deleted)
  bd-twin-t1b  T1 fallback: create from iso_id, then restore the snapshot
               with the ISO still attached (deleted)
At each CHECKPOINT the script waits (up to --checkpoint-wait s) for a file
<checkpoint-dir>/go-<n> so the operator can take console screenshots, then
continues. Evidence: evals/results/real-mode/S5/.
"""
from __future__ import annotations

import argparse
import base64
import ipaddress
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bdvultr import REPO, Api, evidence, load_secrets, set_secret  # noqa: E402
from s4_shop_prod import PLAN, REGION, SSH_KEY, UBUNTU_2404, ssh, ssh_opts, wait_ssh  # noqa: E402

OUT = evidence("S5")
CASE = "case-9001"
JOBS = [
    {"job_id": "job-os-facts", "tool": "os_facts", "args": {}},
    {"job_id": "job-persistence", "tool": "persistence_scan", "args": {}},
    {"job_id": "job-detonate-bdrv", "tool": "detonate", "args": {"path": "usr/local/bin/.bdrv"}},
]


def note(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(OUT / "run.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def checkpoint(n: int, what: str, cdir: Path, wait_s: float) -> None:
    note(f"CHECKPOINT {n}: {what} -- touch {cdir / f'go-{n}'} to continue (max {wait_s:.0f}s)")
    t0 = time.monotonic()
    while not (cdir / f"go-{n}").exists() and time.monotonic() - t0 < wait_s:
        time.sleep(5)


def cp_log(ip: str) -> list[dict]:
    raw = ssh(ip, "sudo cat /root/cp.jsonl 2>/dev/null || true")
    return [json.loads(l) for l in raw.splitlines() if l.strip()]


def wait_register(ip: str, n_expected: int, timeout_s: float) -> list[dict]:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        regs = [e for e in cp_log(ip) if e.get("path") == "/twin/register"]
        if len(regs) >= n_expected:
            return regs
        time.sleep(15)
    return [e for e in cp_log(ip) if e.get("path") == "/twin/register"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--checkpoint-dir", type=Path, default=OUT / "checkpoints")
    ap.add_argument("--checkpoint-wait", type=float, default=900)
    ap.add_argument("--skip-t1a", action="store_true")
    args = ap.parse_args()
    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    env = load_secrets()
    api = Api(env["VULTR_API_KEY"], evidence_dir=OUT)
    iso_id = env["VULTR_ISO_ID"]
    snap_id = json.loads((REPO / "evals/results/real-mode/S4/result.json").read_text())["snapshot_id"]
    pub = subprocess.run(["ssh-keygen", "-y", "-f", str(SSH_KEY)], capture_output=True,
                         text=True, check=True).stdout.strip()
    findings: dict = {"iso_id": iso_id, "snapshot_id": snap_id}
    created: list[tuple[str, str]] = []  # (kind, id) for finally
    try:
        # ---------------------------------------------------------------- VPC
        vpc = None
        if env.get("BD_VPC_ID"):
            s, d = api.call("GET", f"/v2/vpcs/{env['BD_VPC_ID']}", name="get-env-vpc", ok=(404,))
            vpc = d["vpc"] if s == 200 else None
        if vpc is None:
            vpc = api.call("POST", "/v2/vpcs", {"region": REGION, "description": "bd-vpc"},
                           name="create-vpc")[1]["vpc"]
            set_secret("BD_VPC_ID", vpc["id"])
            set_secret("BD_VPC_SUBNET", f"{vpc['v4_subnet']}/{vpc['v4_subnet_mask']}")
            note(f"created bd-vpc {vpc['id']} and saved BD_VPC_ID/BD_VPC_SUBNET")
        net = ipaddress.IPv4Network(f"{vpc['v4_subnet']}/{vpc['v4_subnet_mask']}")
        findings["vpc"] = {"id": vpc["id"], "subnet": str(net)}

        fw = api.call("POST", "/v2/firewalls", {"description": "bd-twin-fw"}, name="create-fw")[1]["firewall_group"]
        created.append(("firewalls", fw["id"]))

        # ------------------------------------------------------------- bd-cp
        cc = ("#cloud-config\nusers:\n  - name: ubuntu\n    groups: sudo\n    shell: /bin/bash\n"
              '    sudo: "ALL=(ALL) NOPASSWD:ALL"\n'
              f"    ssh_authorized_keys:\n      - {pub}\n")
        cp = api.call("POST", "/v2/instances", {
            "region": REGION, "plan": PLAN, "os_id": UBUNTU_2404, "label": "bd-cp", "hostname": "bd-cp",
            "tags": ["body-double"], "attach_vpc": [vpc["id"]], "backups": "disabled",
            "user_data": base64.b64encode(cc.encode()).decode()}, name="create-bd-cp")[1]["instance"]
        created.append(("instances", cp["id"]))
        cp, _ = api.wait(f"/v2/instances/{cp['id']}", "instance", "status", "active", 900, 10)
        cp_ip = cp["main_ip"]
        wait_ssh(cp_ip)
        cp_vpc = api.get(f"/v2/instances/{cp['id']}/vpcs")["vpcs"][0]
        cp_vpc_ip = cp_vpc["ip_address"]
        have = ssh(cp_ip, "ip -4 -o addr").strip()
        if cp_vpc_ip not in have:  # Vultr VPC has no DHCP; set it from the API's answer
            iface = ssh(cp_ip, f"ip -o link | grep -i {cp_vpc['mac_address']} | cut -d: -f2").strip()
            ssh(cp_ip, f"sudo ip link set {iface} up && sudo ip addr add {cp_vpc_ip}/{net.prefixlen} dev {iface}")
        findings["bd_cp"] = {"id": cp["id"], "vpc_ip": cp_vpc_ip,
                             "vpc_ip_auto_configured": cp_vpc_ip in have}
        # how does the metadata service hand back user_data? Real-mode finding
        # (2026-11-15): Vultr's md no longer serves /v1/user-data (403/404); the
        # live endpoint is GET /v1.json with header "Metadata-Token: cloudinit",
        # and its user-data field is the DECODED string (measured on bd-cp).
        md = ssh(cp_ip, "curl -s -m 8 -H 'Metadata-Token: cloudinit' http://169.254.169.254/v1.json")
        served_ud = (json.loads(md).get("user-data") or "")
        # if the service serves what create-time user_data decodes to, then storing
        # base64(X) means the ISO agent (which b64decodes the served bytes) must be
        # handed base64(X) -> create-time value = base64(base64(X)).
        md_serves_decoded = served_ud == "" or served_ud.startswith("{")
        findings["metadata_user_data_is_raw"] = md_serves_decoded
        note(f"bd-cp {cp['id']}: /v1.json user-data served "
             f"{'decoded (double-b64 needed)' if md_serves_decoded else 'as-stored'}")

        tokens = [secrets.token_hex(16) for _ in range(3)]
        (OUT / "jobs.json").write_text(json.dumps(JOBS, indent=2))
        subprocess.run(["scp", *ssh_opts(), "-q", str(REPO / "scripts/cp_stub.py"), str(OUT / "jobs.json"),
                        f"ubuntu@{cp_ip}:/tmp/"], check=True, timeout=120)
        ssh(cp_ip, f"sudo ufw allow from {net} to any port 8000 proto tcp >/dev/null 2>&1 || true")
        ssh(cp_ip, "sudo sh -c 'nohup python3 /tmp/cp_stub.py --bind {ip} --port 8000 --case {case} "
                   "--token {tok} --jobs /tmp/jobs.json --log /root/cp.jsonl >/root/cp.err 2>&1 &'"
            .format(ip=cp_vpc_ip, case=CASE, tok=",".join(tokens)))

        def user_data(token: str, vpc_ip: str) -> str:
            payload = json.dumps({"case_id": CASE, "token": token,
                                  "control_plane": f"http://{cp_vpc_ip}:8000",
                                  "vpc_subnet": str(net), "vpc_ip": vpc_ip})
            inner = base64.b64encode(payload.encode()).decode()   # what the ISO agent b64decodes
            return base64.b64encode(inner.encode()).decode() if md_serves_decoded else inner

        hosts = [str(h) for h in net.hosts() if str(h) != cp_vpc_ip]
        twin_body = {"region": REGION, "plan": PLAN, "tags": ["body-double"], "backups": "disabled",
                     "attach_vpc": [vpc["id"]], "firewall_group_id": fw["id"]}

        # ------------------------------------------------------------- T1 (a)
        if not args.skip_t1a:
            ip_a = hosts[10]
            s, d = api.call("POST", "/v2/instances", {**twin_body, "label": "bd-twin-t1a",
                            "snapshot_id": snap_id, "iso_id": iso_id,
                            "user_data": user_data(tokens[0], ip_a)}, name="T1a-create-snapshot+iso", ok=(400, 422))
            findings["t1a_create_status"] = s
            findings["t1a_create_error"] = d.get("error") if isinstance(d, dict) else d
            if s < 400:
                tid = d["instance"]["id"]
                created.append(("instances", tid))
                t0 = time.monotonic()
                inst, _ = api.wait(f"/v2/instances/{tid}", "instance", "status", "active", 1800, 15)
                findings["t1a_active_s"] = round(time.monotonic() - t0)
                api.call("GET", f"/v2/instances/{tid}/iso", name="T1a-iso-status")
                regs = wait_register(cp_ip, 1, 600)
                findings["t1a_registered"] = bool(regs)
                note(f"T1a twin {tid} active; registrations: {len(regs)}")
                checkpoint(1, f"T1a twin {tid}: screenshot the console (which OS booted?)",
                           args.checkpoint_dir, args.checkpoint_wait)

        # ------------------------------------------------------------- T1 (b)
        ip_b = hosts[11]
        n_before = len(wait_register(cp_ip, 0, 0))
        d = api.call("POST", "/v2/instances", {**twin_body, "label": "bd-twin-t1b", "iso_id": iso_id,
                     "user_data": user_data(tokens[1], ip_b)}, name="T1b-create-from-iso")[1]
        tid = d["instance"]["id"]
        created.append(("instances", tid))
        t0 = time.monotonic()
        api.wait(f"/v2/instances/{tid}", "instance", "status", "active", 1800, 15)
        findings["t1b_iso_active_s"] = round(time.monotonic() - t0)
        regs = wait_register(cp_ip, n_before + 1, 600)
        findings["t1b_blank_disk_registered"] = len(regs) > n_before
        n_before = len(regs)
        api.call("GET", f"/v2/instances/{tid}/iso", name="T1b-iso-before-restore")
        # fresh one-time token for the post-restore boot
        api.call("PATCH", f"/v2/instances/{tid}", {"user_data": user_data(tokens[2], ip_b)},
                 name="T1b-patch-user-data")
        t_restore = time.monotonic()
        api.call("POST", f"/v2/instances/{tid}/restore", {"snapshot_id": snap_id}, name="T1b-restore")
        restore_done = None
        for _ in range(240):  # up to 60 min
            inst = api.get(f"/v2/instances/{tid}")["instance"]
            st = api.get(f"/v2/instances/{tid}/iso")
            if inst["status"] == "active" and inst["server_status"] == "ok" and restore_done is None \
                    and time.monotonic() - t_restore > 60:
                restore_done = time.monotonic() - t_restore
                api.call("GET", f"/v2/instances/{tid}", name="T1b-after-restore")
                api.call("GET", f"/v2/instances/{tid}/iso", name="T1b-iso-after-restore")
                break
            time.sleep(15)
        findings["t2_restore_s"] = round(restore_done) if restore_done else None
        regs = wait_register(cp_ip, n_before + 1, 900)
        findings["t1b_after_restore_registered"] = len(regs) > n_before
        if len(regs) > n_before:
            findings["t2_restore_to_register_s"] = round(time.monotonic() - t_restore)
        note(f"T1b twin {tid}: restore {findings['t2_restore_s']}s, ISO registered after restore: "
             f"{findings['t1b_after_restore_registered']}")
        time.sleep(120)  # let the agent run the queued jobs
        checkpoint(2, f"T1b twin {tid}: screenshot the console (ISO or cloned OS? mount, egress)",
                   args.checkpoint_dir, args.checkpoint_wait)
        log = cp_log(cp_ip)
        (OUT / "cp-log.jsonl").write_text("\n".join(json.dumps(e) for e in log) + "\n")
        findings["registrations"] = [{"src_ip": e["src_ip"], "status": e.get("status"),
                                      "vpc_ip_claimed": (e.get("body") or {}).get("vpc_ip"),
                                      "seal": (e.get("body") or {}).get("seal")}
                                     for e in log if e.get("path") == "/twin/register"]
        findings["results"] = {e["path"].split("/")[3]: e.get("body") for e in log
                               if e.get("path", "").endswith("/result")}
        return 0
    finally:
        for kind, rid in reversed(created):
            try:
                api.call("DELETE", f"/v2/{kind}/{rid}", name=f"cleanup-{kind}", ok=(404, 400, 409, 412))
            except Exception as exc:  # keep cleaning the rest
                note(f"cleanup {kind} {rid} failed: {exc}")
        time.sleep(20)
        for kind, rid in created:
            if kind == "firewalls":  # firewall deletes fail while instances still hold it
                api.call("DELETE", f"/v2/{kind}/{rid}", name="cleanup-fw-retry", ok=(404, 400, 409, 412))
        (OUT / "findings.json").write_text(json.dumps(findings, indent=2))
        note("cleanup done; findings.json written")


if __name__ == "__main__":
    sys.exit(main())
