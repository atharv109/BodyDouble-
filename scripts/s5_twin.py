"""S5: day-one tests T1-T4 against real Vultr, one run, cleaned up in `finally`.

    uv run python scripts/s5_twin.py [--checkpoint-dir DIR] [--checkpoint-wait 900]

Creates (all tagged body-double / described bd-*):
  bd-vpc       the shared investigation VPC; reused from BD_VPC_ID if alive,
               else created and saved to BD_VPC_ID/BD_VPC_SUBNET (kept, $0/hr)
  bd-twin-fw   firewall group with no accept rules = inbound deny (deleted)
  bd-cp        Ubuntu VM in the VPC running scripts/cp_stub.py (deleted)
  bd-twin-t1a  T1: ONE create call with snapshot_id AND iso_id (deleted)
  bd-twin-t1b  T1 fallback: create from iso_id, set the API-assigned VPC IP
               in user_data + reboot (ISO boot registers), restore the snapshot,
               then detach + re-attach the ISO so the post-restore boot is the
               ISO agent with the clone mounted inert (deleted)
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


def checkpoint(n: int, what: str, cdir: Path, wait_s: float, twin_id: str = "") -> bool:
    """BLOCKING: write console-url.txt for the orchestrator, then wait until it
    saves its screenshot and creates <cdir>/go-<n> (or wait_s passes). The
    twin is only deleted after this returns. Returns True if go-<n> appeared."""
    url = f"https://my.vultr.com/subs/vps/novnc/?id={twin_id}" if twin_id else "(no instance)"
    go = cdir / f"go-{n}"
    (cdir / "console-url.txt").write_text(
        f"checkpoint {n}\nconsole: {url}\ninstance page: https://my.vultr.com/subs/?id={twin_id}\n"
        f"expected on screen: {what}\n"
        f"save the PNG in {cdir} and then create {go.name} there to continue\n", encoding="utf-8")
    note(f"CHECKPOINT {n}: STOP FOR ORCHESTRATOR: {url} -- {what}; waiting up to "
         f"{wait_s:.0f}s for {go}")
    t0 = time.monotonic()
    while time.monotonic() - t0 < wait_s:
        if go.exists():
            note(f"CHECKPOINT {n}: {go.name} found after {time.monotonic() - t0:.0f}s; continuing")
            return True
        time.sleep(10)
    note(f"CHECKPOINT {n}: no {go.name} after {wait_s:.0f}s; continuing without screenshot")
    return False


def cp_log(ip: str) -> list[dict]:
    # transient SSH drops must not kill the run (run 2 died here)
    raw = ssh(ip, "sudo cat /root/cp.jsonl 2>/dev/null || true", check=False)
    return [json.loads(l) for l in raw.splitlines() if l.strip()]


def wait_register(ip: str, n_expected: int, timeout_s: float) -> list[dict]:
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        regs = [e for e in cp_log(ip) if e.get("path") == "/twin/register"]
        if len(regs) >= n_expected:
            return regs
        time.sleep(15)
    return [e for e in cp_log(ip) if e.get("path") == "/twin/register"]


def wait_results(ip: str, n_expected: int, timeout_s: float) -> list[dict]:
    t0 = time.monotonic()
    while True:
        res = [e for e in cp_log(ip) if e.get("path", "").endswith("/result")]
        if len(res) >= n_expected or time.monotonic() - t0 > timeout_s:
            return res
        time.sleep(15)


def iso_state(api: Api, tid: str, name: str) -> str:
    return api.call("GET", f"/v2/instances/{tid}/iso", name=name)[1]["iso_status"].get("state", "")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="", help="evidence subfolder of S5/ (fresh numbering), e.g. run4")
    ap.add_argument("--checkpoint-dir", type=Path, default=None, help="default: S5/checkpoints")
    ap.add_argument("--checkpoint-wait", type=float, default=1200)
    ap.add_argument("--skip-t1a", action="store_true")
    args = ap.parse_args()
    global OUT
    if args.batch:  # Api numbers files from 001 per process: never overwrite an older run
        OUT = OUT / args.batch
        OUT.mkdir(parents=True, exist_ok=True)
    args.checkpoint_dir = args.checkpoint_dir or OUT / "checkpoints"
    args.checkpoint_dir.mkdir(parents=True, exist_ok=True)
    for stale in args.checkpoint_dir.glob("go-*"):  # a go-file must come from THIS run
        stale.unlink()
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
        findings["_cp_ip"] = cp_ip  # finally saves the stub log before deleting bd-cp
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
        (OUT / "jobs-none.json").write_text("[]\n")
        subprocess.run(["scp", *ssh_opts(), "-q", str(REPO / "scripts/cp_stub.py"), str(OUT / "jobs.json"),
                        str(OUT / "jobs-none.json"), f"ubuntu@{cp_ip}:/tmp/"], check=True, timeout=120)
        ssh(cp_ip, f"sudo ufw allow from {net} to any port 8000 proto tcp >/dev/null 2>&1 || true")

        def start_stub(toks: list[str], jobs_file: str) -> None:
            # restart = fresh tokens, sessions and queue; the JSONL log is appended
            ssh(cp_ip, "sudo pkill -f cp_stub.py; sleep 1", check=False)
            ssh(cp_ip, "sudo sh -c 'nohup python3 /tmp/cp_stub.py --bind {ip} --port 8000 --case {case} "
                       "--token {tok} --jobs /tmp/{jobs} --log /root/cp.jsonl >>/root/cp.err 2>&1 &'"
                .format(ip=cp_vpc_ip, case=CASE, tok=",".join(toks), jobs=jobs_file))

        # phase 1 (blank-disk ISO boots): no jobs, so nothing is spent on an empty disk
        start_stub(tokens[:2], "jobs-none.json")

        def user_data(token: str, vpc_ip: str) -> str:
            payload = json.dumps({"case_id": CASE, "token": token,
                                  "control_plane": f"http://{cp_vpc_ip}:8000",
                                  "vpc_subnet": str(net), "vpc_ip": vpc_ip})
            # stored as b64(payload): the ISO agent's decode_bootstrap unwraps
            # base64-until-JSON (max 3), so it passes whether Vultr serves the
            # field DECODED (run 1) or AS-STORED (run 2) - measured both ways.
            return base64.b64encode(payload.encode()).decode()

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
                checkpoint(1, "console: which OS booted? (Alpine ISO vs Ubuntu clone)", args.checkpoint_dir,
                           args.checkpoint_wait, twin_id=tid)

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
        # Real-mode finding (run 4): Vultr assigns the twin's VPC IP itself and the VPC
        # only delivers to that IP; a self-chosen hosts[11] never answered ARP
        # (run4/vpc-probe-from-bd-cp.txt). The IP is only known after create, so
        # write it into user_data and reboot; the blank disk falls through to the CD.
        ip_b = api.call("GET", f"/v2/instances/{tid}/vpcs", name="T1b-twin-vpcs")[1]["vpcs"][0]["ip_address"]
        findings["t4_twin_vpc_ip_from_api"] = ip_b
        api.call("PATCH", f"/v2/instances/{tid}", {"user_data": user_data(tokens[1], ip_b)},
                 name="T1b-patch-user-data-blank")
        api.call("POST", f"/v2/instances/{tid}/reboot", name="T1b-reboot-blank")
        regs = wait_register(cp_ip, n_before + 1, 600)
        findings["t1b_blank_disk_registered"] = len(regs) > n_before
        note(f"T1b twin {tid} (VPC {ip_b}): blank-disk ISO boot registered: "
             f"{findings['t1b_blank_disk_registered']}; starting restore")
        n_before = len(regs)
        iso_state(api, tid, "T1b-iso-before-restore")
        # phase 2: only the post-restore boot's token is valid and the 3 jobs wait for it
        start_stub(tokens[2:], "jobs.json")
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
        # re-apply after the restore so the snapshot cannot bring back old user_data
        api.call("PATCH", f"/v2/instances/{tid}", {"user_data": user_data(tokens[2], ip_b)},
                 name="T1b-patch-user-data-after-restore")
        # Real-mode finding (run 4): after restore the API still says "isomounted"
        # (run4/044) but the console shows the Ubuntu clone booted from disk
        # (S5/checkpoints/console-2-take1.png): a bootable disk wins the boot order.
        # Detach + re-attach the ISO; attach reboots the instance from the ISO.
        api.call("POST", f"/v2/instances/{tid}/iso/detach", name="T1b-iso-detach")
        for _ in range(40):
            if iso_state(api, tid, "T1b-iso-after-detach") != "isomounted":
                break
            time.sleep(15)
        # attach is POST /iso (only detach has a /detach suffix)
        api.call("POST", f"/v2/instances/{tid}/iso", {"iso_id": iso_id}, name="T1b-iso-attach")
        for _ in range(40):
            if iso_state(api, tid, "T1b-iso-after-attach") == "isomounted":
                break
            time.sleep(15)
        findings["t1b_iso_reattached"] = iso_state(api, tid, "T1b-iso-reattached") == "isomounted"
        note(f"T1b twin {tid}: restore {findings['t2_restore_s']}s; ISO re-attached: "
             f"{findings['t1b_iso_reattached']}; waiting for the post-restore registration")
        regs = wait_register(cp_ip, n_before + 1, 900)
        findings["t1b_after_restore_registered"] = len(regs) > n_before
        if len(regs) > n_before:
            findings["t2_restore_to_register_s"] = round(time.monotonic() - t_restore)
        note(f"T1b twin {tid}: restore {findings['t2_restore_s']}s, ISO registered after restore: "
             f"{findings['t1b_after_restore_registered']}")
        res = wait_results(cp_ip, len(JOBS), 900)  # the agent runs the 3 queued jobs
        findings["t3_results_received"] = len(res)
        note(f"T3: {len(res)}/{len(JOBS)} job results received")
        findings["checkpoint_2_go"] = checkpoint(
            2, "Alpine ISO console on tty0 (not Ubuntu login) with boot.sh lines: 'bd: no serial "
               "console; boot messages on tty0', 'bd-vpc-up: <vpc_ip>/20 on "
               "eth1', 'bd: cloned disk /dev/vda1 mounted inert and read-only at /mnt/disk', "
               "'bd: sandbox image loaded; runtimes: ...runsc...'",
            args.checkpoint_dir, args.checkpoint_wait, twin_id=tid)
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
        # run 6 lost bd-cp's log to a mid-run kill: always keep it before deleting bd-cp
        cp_ip = findings.pop("_cp_ip", None)
        if cp_ip and not (OUT / "cp-log.jsonl").exists():
            try:
                log = cp_log(cp_ip)
                (OUT / "cp-log.jsonl").write_text("\n".join(json.dumps(e) for e in log) + "\n")
                findings.setdefault("registrations", [
                    {"src_ip": e["src_ip"], "status": e.get("status"),
                     "vpc_ip_claimed": (e.get("body") or {}).get("vpc_ip"),
                     "seal": (e.get("body") or {}).get("seal")}
                    for e in log if e.get("path") == "/twin/register"])
                findings.setdefault("results", {e["path"].split("/")[3]: e.get("body") for e in log
                                                if e.get("path", "").endswith("/result")})
            except Exception as exc:
                note(f"saving cp-log failed: {exc}")
        for kind, rid in reversed(created):
            for attempt in range(3):  # run 4: a local DNS blip left the twin running
                try:
                    api.call("DELETE", f"/v2/{kind}/{rid}", name=f"cleanup-{kind}", ok=(404, 400, 409, 412))
                    break
                except Exception as exc:  # keep cleaning the rest
                    note(f"cleanup {kind} {rid} attempt {attempt + 1} failed: {exc}")
                    time.sleep(20)
        time.sleep(20)
        for kind, rid in created:
            if kind == "firewalls":  # firewall deletes fail while instances still hold it
                api.call("DELETE", f"/v2/{kind}/{rid}", name="cleanup-fw-retry", ok=(404, 400, 409, 412))
        (OUT / "findings.json").write_text(json.dumps(findings, indent=2))
        note("cleanup done; findings.json written")


if __name__ == "__main__":
    sys.exit(main())
