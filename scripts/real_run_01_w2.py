"""W2 (Gate 2): can the twin come up with NO outbound path? Live probes, every
response saved under evals/results/real-run-01/preswap-isolation/.

    uv run python scripts/real_run_01_w2.py            # launched detached
    uv run python scripts/real_run_01_w2.py --skip-restore-on-halt

Probes, in order of execution:
  A  POST /v2/instances {os_id, attach_vpc} — plain VPC-only create: does a
     public IPv4 still come? (live attempt + GET fields + in-VM egress test)
  E  out-direction firewall rules: accept-out to the VPC :22, then drop-all-out
     0.0.0.0/0 — is the instance network-dead to the internet while it still
     runs and the VPC still reaches it? (in-VM egress re-test before/after)
  D  POST halt right after create; power_status; restore-while-halted
  B  POST /v2/instances {..., "disable_public_ipv4": true} — schema check +
     live attempt (this is the real prize for the run-13 flow)
  C  POST /v2/instances {..., "power_on": false} — schema check only

Every created resource is deleted in finally. findings.md (the analysis, with
what the API accepted/rejected verbatim) is written by the worker afterwards.
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bdvultr import REPO, Api, load_secrets  # noqa: E402
from s4_shop_prod import PLAN, REGION, SSH_KEY, UBUNTU_2404, ssh, ssh_opts, wait_ssh  # noqa: F401  # noqa: E402

OUT = REPO / "evals/results/real-run-01/preswap-isolation"
SNAP = json.loads((REPO / "evals/results/real-mode/S4/result.json").read_text())["snapshot_id"]


def note(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(OUT / "w2-run.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def in_vm(ip: str, cmd: str) -> str:
    return ssh(ip, cmd, check=False).strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--skip-restore-on-halt", action="store_true",
                    help="omit probe D's ~5 min restore (still probes the halt)")
    args = ap.parse_args()
    env = load_secrets()
    api = Api(env["VULTR_API_KEY"], evidence_dir=OUT)
    vpc_id = env["BD_VPC_ID"]
    pub = subprocess.run(["ssh-keygen", "-y", "-f", str(SSH_KEY)],
                         capture_output=True, text=True, check=True).stdout.strip()
    cc = ("#cloud-config\nusers:\n  - name: ubuntu\n    groups: sudo\n    shell: /bin/bash\n"
          '    sudo: "ALL=(ALL) NOPASSWD:ALL"\n'
          f"    ssh_authorized_keys:\n      - {pub}\n")
    ud = base64.b64encode(cc.encode()).decode()
    created: list[tuple[str, str]] = []
    inst_a: str | None = None
    try:
        # -------------------------------------------------- A: plain VPC-only
        fw = api.call("POST", "/v2/firewalls", {"description": "bd-w2-fw"},
                      name="create-fw")[1]["firewall_group"]
        created.append(("firewalls", fw["id"]))
        # inbound :22 from anywhere so the disposable probe box is testable;
        # outbound (the W2 question) starts unrestricted
        api.call("POST", f"/v2/firewalls/{fw['id']}/rules",
                 {"action": "accept", "direction": "in", "ip_type": "v4", "protocol": "tcp",
                  "subnet": "0.0.0.0/0", "subnet_size": 0, "port": "22"},
                 name="fw-in-accept-22")
        body_a = {"region": REGION, "plan": PLAN, "os_id": UBUNTU_2404,
                  "label": "bd-w2-vpconly", "hostname": "bd-w2-vpconly",
                  "tags": ["body-double"], "backups": "disabled",
                  "attach_vpc": [vpc_id], "firewall_group_id": fw["id"], "user_data": ud}
        inst = api.call("POST", "/v2/instances", body_a, name="A-create-vpc-only")[1]["instance"]
        inst_a = inst["id"]
        created.append(("instances", inst_a))
        inst, _ = api.wait(f"/v2/instances/{inst_a}", "instance", "status", "active", 900, 10)
        fields = {k: inst.get(k) for k in ("main_ip", "vpc_ids", "internal_ip", "region", "plan")}
        note(f"A: created VPC-only; fields={json.dumps(fields)}; waiting sshd")
        wait_ssh(inst["main_ip"])
        egress0 = in_vm(inst["main_ip"],
                        "curl -sS -m 8 -o /dev/null -w 'http=%{http_code}' https://api.ipify.org && "
                        "echo \" egress_ip=$(curl -sS -m 8 https://api.ipify.org)\"")
        egress0_pub = in_vm(inst["main_ip"], "ip -4 -brief addr show")
        (OUT / "A-vm-ifaces-and-egress.txt").write_text(
            f"before any out-rule:\n$ ip -4 -brief addr\n{egress0_pub}\n"
            f"$ curl https://api.ipify.org\n{egress0}\n", encoding="utf-8")
        note(f"A: baseline egress from the VPC-only instance: {egress0!r}")

        # --------------- E: out-direction rules (network-dead while running)
        drop_rule_id = None
        api.call("POST", f"/v2/firewalls/{fw['id']}/rules",
                 {"action": "accept", "direction": "out", "ip_type": "v4", "protocol": "tcp",
                  "subnet": (inst.get("internal_ip") or "10.1.96.4").rsplit(".", 1)[0] + ".0",
                  "subnet_size": 20, "port": "22"},
                 name="E1-out-accept-vpc-22", ok=(400, 422))
        s_drop, d_drop = api.call(
            "POST", f"/v2/firewalls/{fw['id']}/rules",
            {"action": "drop", "direction": "out", "ip_type": "v4", "protocol": "tcp",
             "subnet": "0.0.0.0/0", "subnet_size": 0, "port": ""},
            name="E2-out-drop-all-port-empty", ok=(400, 422))
        if s_drop >= 400:  # port "" refused? retry the documented range form
            s_drop, d_drop = api.call(
                "POST", f"/v2/firewalls/{fw['id']}/rules",
                {"action": "drop", "direction": "out", "ip_type": "v4", "protocol": "tcp",
                 "subnet": "0.0.0.0/0", "subnet_size": 0, "port": "1-65535"},
                name="E2b-out-drop-all-port-range", ok=(400, 422))
        if s_drop < 400 and isinstance(d_drop, dict):
            drop_rule_id = (d_drop.get("firewall_rule") or {}).get("id")
        rules_now = api.get(f"/v2/firewalls/{fw['id']}/rules")
        (OUT / "E3-rules-after.json").write_text(json.dumps(rules_now, indent=2), encoding="utf-8")
        if s_drop < 400:
            time.sleep(10)  # firewall rules converge in a few seconds
            egress1 = in_vm(inst["main_ip"],
                            "curl -sS -m 8 -o /dev/null -w 'http=%{http_code}' https://api.ipify.org; "
                            "echo \" rc=$?\"; ping -c 1 -W 3 8.8.8.8 2>&1 | tail -1; "
                            "echo done $(date -u +%FT%T.%NZ)")
            (OUT / "E4-egress-after-out-rules.txt").write_text(egress1 + "\n", encoding="utf-8")
            note(f"E: in-VM egress after out-rules: {egress1!r}")
            if drop_rule_id:
                api.call("DELETE", f"/v2/firewalls/{fw['id']}/rules/{drop_rule_id}",
                         name="E5-delete-out-drop", ok=(404,))
                time.sleep(10)
            egress2 = in_vm(inst["main_ip"],
                            "curl -sS -m 8 -o /dev/null -w 'http=%{http_code}' https://api.ipify.org; "
                            "echo \" rc=$?\"")
            (OUT / "E6-egress-after-rule-delete.txt").write_text(egress2 + "\n", encoding="utf-8")
            note(f"E: egress after deleting the drop rule: {egress2!r}")

        # ------------------------------------- D: halt right after create?
        api.call("POST", f"/v2/instances/{inst_a}/halt", name="D1-halt")
        pw = None
        for _ in range(30):
            pw = api.get(f"/v2/instances/{inst_a}")["instance"].get("power_status")
            if pw == "stopped":
                break
            time.sleep(10)
        note(f"D: after halt, power_status={pw!r}")
        (OUT / "D2-power-after-halt.txt").write_text(f"power_status={pw}\n", encoding="utf-8")
        if not args.skip_restore_on_halt:
            s_r, d_r = api.call("POST", f"/v2/instances/{inst_a}/restore",
                                {"snapshot_id": SNAP}, name="D3-restore-while-halted",
                                ok=(400, 409, 412, 422))
            note(f"D: restore on the halted instance -> {s_r}: "
                 f"{json.dumps(d_r)[:300] if d_r else '-'}")
            (OUT / "D3-restore-while-halted.json").write_text(
                json.dumps({"status": s_r, "response": d_r}, indent=2), encoding="utf-8")
            time.sleep(15)
            pw2 = api.get(f"/v2/instances/{inst_a}")["instance"].get("power_status")
            (OUT / "D4-power-after-restore.txt").write_text(f"power_status={pw2}\n", encoding="utf-8")
            note(f"D: power_status after restore = {pw2!r}")

        # ----------------------------------------- B: disable_public_ipv4
        body_b = {**body_a, "label": "bd-w2-nopub", "hostname": "bd-w2-nopub",
                  "disable_public_ipv4": True}
        del body_b["firewall_group_id"]
        s_b, d_b = api.call("POST", "/v2/instances", body_b,
                            name="B-create-disable-public-ipv4", ok=(400, 422))
        note(f"B: create with disable_public_ipv4 -> {s_b}")
        if s_b < 400:
            iid = d_b["instance"]["id"]
            created.append(("instances", iid))
            inst_b, _ = api.wait(f"/v2/instances/{iid}", "instance", "status", "active", 900, 10)
            fields_b = {k: inst_b.get(k) for k in
                        ("main_ip", "vpc_ids", "internal_ip", "server_status", "power_status")}
            api.call("GET", f"/v2/instances/{iid}/vpcs", name="B-instance-vpcs")
            (OUT / "B-fields-after-create.json").write_text(
                json.dumps(fields_b, indent=2), encoding="utf-8")
            note(f"B: ACTIVE with disable_public_ipv4; fields={json.dumps(fields_b)}")
            # no public IP -> no direct SSH; the egress question for this shape is
            # architectural (VPC has no internet route) and is settled in findings.md

        # ---------------------------------------------- C: power_on false
        body_c = {**body_a, "label": "bd-w2-powerflag", "hostname": "bd-w2-powerflag",
                  "power_on": False}
        s_c, d_c = api.call("POST", "/v2/instances", body_c,
                            name="C-create-power-on-false", ok=(400, 422))
        note(f"C: create with power_on=False -> {s_c}")
        if s_c < 400:  # silently ignored would also land here: record the fields
            iid = d_c["instance"]["id"]
            created.append(("instances", iid))
            inst_c = api.get(f"/v2/instances/{iid}")["instance"]
            (OUT / "C-fields-after-create.json").write_text(json.dumps({
                "power_status": inst_c.get("power_status"),
                "server_status": inst_c.get("server_status")}, indent=2), encoding="utf-8")
        return 0
    finally:
        for kind, rid in reversed(created):
            try:  # retries 409 'locked' (mid-restore): one 409 leaked fb0dd8a4
                api.delete_until_gone(f"/v2/{kind}/{rid}", name=f"cleanup-{kind}")
            except Exception as exc:
                note(f"CLEANUP FAILED {kind} {rid}: {exc} -- run scripts/vultr_sweep.py")
        note("W2 probes cleaned up")


if __name__ == "__main__":
    sys.exit(main())
