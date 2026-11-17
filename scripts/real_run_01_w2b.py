"""W2b (Gate 2): follow-ups from the first W2 probes.

W2 round one found (evals/results/real-run-01/preswap-isolation/):
  * disable_public_ipv4: true -> 400 "The selected VPC does not have a NAT
    gateway. Deploy a NAT gateway on this VPC before creating a VPC-only
    instance."  => VPC-only instances ARE supported, gated on a NAT gateway.
  * out-direction firewall rule action=drop -> 201 but stored as accept
    (silently coerced; egress stayed 200). Outbound deny is NOT available.
  * power_on: false -> silently ignored (power_status running).
  * restore on a halted instance -> 202 accepted; power stayed stopped 15 s in.

This driver settles the remaining questions, saving every response to
evals/results/real-run-01/preswap-isolation/:
  N  NAT gateway create attempts on bd-vpc (endpoint + body shape discovery)
  B2 VPC-only instance (disable_public_ipv4) once the NAT gateway exists:
     fields, and in-VM egress reached over the VPC from a jump host —
     WITH the NAT gateway, then AFTER deleting it (the isolation question)
  D2 restore-on-halted completion tail: when does power_status flip?

Every created resource is deleted in finally.
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from bdvultr import REPO, Api, load_secrets  # noqa: E402
from s4_shop_prod import PLAN, REGION, SSH_KEY, UBUNTU_2404, ssh_opts, wait_ssh  # noqa: E402

OUT = REPO / "evals/results/real-run-01/preswap-isolation" / (  # fresh numbering per run
    "w2b-d2" if "--only-d2" in sys.argv else "w2b-run2")
SNAP = json.loads((REPO / "evals/results/real-mode/S4/result.json").read_text())["snapshot_id"]
EGRESS_CMD = ("curl -sS -m 8 -o /dev/null -w 'https443 http=%{http_code}' https://api.ipify.org; "
              "echo \" rc=$?\"; curl -sS -m 8 https://api.ipify.org; echo; "
              "getent hosts example.com >/dev/null; echo \"dns53 rc=$?\"; "
              "ping -c 1 -W 3 8.8.8.8 2>&1 | tail -1")


def note(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(OUT / "w2b-run.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def jump_ssh(jump_ip: str, target_ip: str, cmd: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """SSH to the VPC-only instance through the public jump host."""
    jump = " ".join(["ssh", *ssh_opts(), "-W", "%h:%p", f"ubuntu@{jump_ip}"])
    p = subprocess.run(["ssh", *ssh_opts(), "-o", f"ProxyCommand={jump}", f"ubuntu@{target_ip}", cmd],
                       capture_output=True, timeout=timeout)
    return subprocess.CompletedProcess(p.args, p.returncode, p.stdout.decode(errors="replace"),
                                       p.stderr.decode(errors="replace"))


def main() -> int:
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
    fw_id = None
    try:
        fw = api.call("POST", "/v2/firewalls", {"description": "bd-w2b-fw"},
                      name="create-fw")[1]["firewall_group"]
        fw_id = fw["id"]
        created.append(("firewalls", fw_id))
        api.call("POST", f"/v2/firewalls/{fw_id}/rules",
                 {"action": "accept", "direction": "in", "ip_type": "v4", "protocol": "tcp",
                  "subnet": "0.0.0.0/0", "subnet_size": 0, "port": "22"}, name="fw-in-accept-22")

        if "--only-d2" not in sys.argv:
            run_nat_probes(api, vpc_id, fw_id, ud, created)
        run_d2(api, fw_id, ud, created)
        return 0
    finally:
        cleanup(api, vpc_id, created)


def run_nat_probes(api: Api, vpc_id: str, fw_id: str, ud: str, created: list) -> None:
    # ------------------------------- N: NAT gateway create (shape search)
    attempts = [
        ("POST", "/v2/nat-gateways", {"region": REGION, "vpc_id": vpc_id, "label": "bd-natgw"}),
        ("POST", "/v2/nat-gateways", {"region": REGION, "vpc_id": vpc_id, "description": "bd-natgw"}),
        ("POST", f"/v2/vpcs/{vpc_id}/nat-gateway", {"region": REGION, "label": "bd-natgw"}),
    ]
    nat = None
    for i, (m, path, body) in enumerate(attempts):
        s, d = api.call(m, path, body, name=f"N{i}-nat-create-attempt", ok=tuple(range(400, 600)))
        note(f"N{i}: {m} {path} -> {s}: {json.dumps(d)[:200] if d else '-'}")
        if s < 400:
            nat = d.get("nat_gateway") or d
            break
    if nat is None:
        raise RuntimeError("no NAT gateway create endpoint accepted any known body shape; "
                           "see N*.json for the verbatim errors")
    nat_id = nat["id"]
    created.append(("nat-gateways", nat_id))
    nat_status = nat.get("gateway_status") or nat.get("status")
    t0 = time.monotonic()
    while nat_status not in ("active", "enabled", None) and time.monotonic() - t0 < 600:
        time.sleep(15)
        # the NAT gateway lives under the VPC (POST /v2/nat-gateways is 404)
        nat = next((n for n in api.get(f"/v2/vpcs/{vpc_id}/nat-gateway").get("nat_gateways", [])
                    if n["id"] == nat_id), {})
        nat_status = nat.get("gateway_status") or nat.get("status")
    note(f"NAT gateway {nat_id} status={nat_status!r} after {time.monotonic()-t0:.0f}s")

    # --------------------------------- B2: VPC-only instance, live fields
    body = {"region": REGION, "plan": PLAN, "os_id": UBUNTU_2404, "label": "bd-w2b-vpconly",
            "hostname": "bd-w2b-vpconly", "tags": ["body-double"], "backups": "disabled",
            "attach_vpc": [vpc_id], "firewall_group_id": fw_id,
            "disable_public_ipv4": True, "user_data": ud}
    inst = api.call("POST", "/v2/instances", body, name="B2-create-vpc-only-with-natgw",
                    ok=(400, 422))[1]
    if "instance" not in inst:
        note(f"B2: create STILL refused: {json.dumps(inst)[:200]}")
        raise RuntimeError("VPC-only create refused again; see B2 response")
    iid = inst["instance"]["id"]
    created.append(("instances", iid))
    inst, _ = api.wait(f"/v2/instances/{iid}", "instance", "status", "active", 900, 10)
    fields = {k: inst.get(k) for k in ("main_ip", "vpc_ids", "internal_ip", "region", "plan")}
    (OUT / "B2-fields.json").write_text(json.dumps(fields, indent=2), encoding="utf-8")
    note(f"B2: VPC-only instance ACTIVE with NATGW; fields={json.dumps(fields)}")

    # jump host (public) then reach the VPC-only instance over the VPC
    jbody = {"region": REGION, "plan": PLAN, "os_id": UBUNTU_2404, "label": "bd-w2b-jump",
             "hostname": "bd-w2b-jump", "tags": ["body-double"], "backups": "disabled",
             "attach_vpc": [vpc_id], "user_data": ud}
    jump = api.call("POST", "/v2/instances", jbody, name="B2-create-jump")[1]["instance"]
    created.append(("instances", jump["id"]))
    jump, _ = api.wait(f"/v2/instances/{jump['id']}", "instance", "status", "active", 900, 10)
    jump_ip = jump["main_ip"]
    wait_ssh(jump_ip)
    vpc_ip = api.call("GET", f"/v2/instances/{iid}/vpcs", name="B2-instance-vpcs")[1]["vpcs"][0]["ip_address"]
    note(f"B2: jump {jump_ip} up; VPC-only instance at VPC {vpc_ip}; probing egress WITH NATGW")
    for _ in range(20):
        p = jump_ssh(jump_ip, vpc_ip, "cloud-init status --wait >/dev/null 2>&1; echo up")
        if p.returncode == 0:
            break
        time.sleep(15)
    e1 = jump_ssh(jump_ip, vpc_ip, EGRESS_CMD, timeout=120)
    (OUT / "B2-egress-WITH-natgw.txt").write_text(
        f"from VPC-only instance (no public IPv4), NAT gateway present:\n"
        f"$ {EGRESS_CMD}\nrc={e1.returncode}\n{e1.stdout}{e1.stderr}\n", encoding="utf-8")
    note(f"B2: egress WITH natgw rc={e1.returncode}: {e1.stdout.strip()[:200]!r}")

    # ------------------------------ the isolation question: delete NATGW
    s_del, d_del = api.call("DELETE", f"/v2/vpcs/{vpc_id}/nat-gateway/{nat_id}",
                            name="B3-delete-natgw", ok=(422,))
    note(f"B3: delete NATGW with the VPC-only instance alive -> {s_del}: {json.dumps(d_del)[:200]}")
    if s_del >= 400:  # run 2: 422 'remove all VPC-only instances ... first'
        return
    created[:] = [(k, r) for k, r in created if r != nat_id]
    nat_id = None
    time.sleep(30)  # route teardown
    e2 = jump_ssh(jump_ip, vpc_ip, EGRESS_CMD, timeout=120)
    (OUT / "B2-egress-AFTER-natgw-delete.txt").write_text(
        f"from VPC-only instance, NAT gateway DELETED:\n$ {EGRESS_CMD}\n"
        f"rc={e2.returncode}\n{e2.stdout}{e2.stderr}\n", encoding="utf-8")
    note(f"B2: egress AFTER natgw delete rc={e2.returncode}: {e2.stdout.strip()[:200]!r}")



def run_d2(api: Api, fw_id: str, ud: str, created: list) -> None:
    # ------------------------------- D2: restore-on-halted completion
    dbody = {"region": REGION, "plan": PLAN, "os_id": UBUNTU_2404, "label": "bd-w2b-haltrestore",
             "hostname": "bd-w2b-haltrestore", "tags": ["body-double"], "backups": "disabled",
             "firewall_group_id": fw_id, "user_data": ud}
    d = api.call("POST", "/v2/instances", dbody, name="D2-create-haltrestore")[1]["instance"]
    created.append(("instances", d["id"]))
    # halt while pending -> 409 'Cannot stop server while it is pending' (w2b-d2/try1)
    api.wait(f"/v2/instances/{d['id']}", "instance", "status", "active", 900, 10)
    for _ in range(20):
        if api.call("POST", f"/v2/instances/{d['id']}/halt", name="D2-halt", ok=(409,))[0] < 400:
            break
        time.sleep(15)
    for _ in range(30):
        if api.get(f"/v2/instances/{d['id']}")["instance"].get("power_status") == "stopped":
            note("D2: instance stopped; issuing restore")
            break
        time.sleep(10)
    t_r = time.monotonic()
    api.call("POST", f"/v2/instances/{d['id']}/restore", {"snapshot_id": SNAP},
             name="D2-restore-halted")
    timeline = []
    for _ in range(40):  # up to ~10 min: when does it boot after the restore?
        inst_d = api.get(f"/v2/instances/{d['id']}")["instance"]
        line = (f"{time.strftime('%H:%M:%S')} +{time.monotonic()-t_r:.0f}s "
                f"power={inst_d.get('power_status')} server_status={inst_d.get('server_status')} "
                f"status={inst_d.get('status')}")
        timeline.append(line)
        if inst_d.get("power_status") == "running":
            break
        time.sleep(15)
    (OUT / "D2-restore-halted-timeline.txt").write_text("\n".join(timeline) + "\n", encoding="utf-8")
    note(f"D2: restore-on-halted tail recorded ({len(timeline)} samples)")


def cleanup(api: Api, vpc_id: str, created: list) -> None:
    for kind, rid in reversed(created):
        # NAT gateways live under their VPC: /v2/nat-gateways/{id} is 404 (leaked 62f6fe13)
        path = (f"/v2/vpcs/{vpc_id}/nat-gateway/{rid}" if kind == "nat-gateways"
                else f"/v2/{kind}/{rid}")
        try:  # retries 409 'locked' (mid-restore): one 409 leaked fb0dd8a4
            api.delete_until_gone(path, name=f"cleanup-{kind}")
        except Exception as exc:
            note(f"CLEANUP FAILED {kind} {rid}: {exc} -- run scripts/vultr_sweep.py")
    note("W2b probes cleaned up")


if __name__ == "__main__":
    sys.exit(main())
