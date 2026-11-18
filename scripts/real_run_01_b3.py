"""B3 (Gate 2): ONE real case end-to-end through the control plane (BD_REAL_MODE=1).

    uv run python scripts/real_run_01_b3.py      # launch detached; evidence -> evals/results/real-run-01/b3/

Flow (orchestrator decisions, 2026-11-17):
  * bd-cp: Ubuntu VM in the investigation VPC with a RESERVED IPv4 (label bd-cp-ip,
    id saved to BD_CP_RESERVED_IP_ID). The Vultr key's IP allowlist must contain it:
    the driver checks from bd-cp and otherwise writes checkpoints/bd-cp-ip.txt and
    waits for checkpoints/go-allowlist (the orchestrator relays the panel add).
  * The REAL backend runs on bd-cp (committed code via `git archive HEAD`), env
    secrets over SSH stdin to a 0600 file, never printed. :8000 is reachable only
    from the VPC (the twin) and loopback (the operator's SSH tunnel).
  * shop-prod is created from snapshot ef199a06 (S4); POST /cases runs the whole
    pipeline (snapshot -> twin -> seal -> real investigator -> report -> close).
  * The ESP swap is done OUT-OF-BAND by this driver, exactly as in run 13, while the
    backend waits for the sealed registration: the control plane never holds an
    SSH key into the clone. Trigger: the clone's post-ISO-attach boot (sshd up, sr0
    labelled BDFORENSICS, same boot_id 30 s apart).
  * After close: bundle + hash-chain verify, GET on the twin -> 404, healthz.
Cleanup in finally: shop-prod, bd-cp, the case's snapshot, leftover twins/firewalls.
The reserved IP is kept for reruns (sweep keeps BD_CP_RESERVED_IP_ID).
"""
from __future__ import annotations

import base64
import io
import json
import secrets
import subprocess
import sys
import threading
import time
import zipfile
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).parent))
from bdvultr import REPO, Api, load_secrets, set_secret  # noqa: E402
from s4_shop_prod import PLAN, REGION, SSH_KEY, UBUNTU_2404, ssh, ssh_opts, wait_ssh  # noqa: E402
import s5_twin  # noqa: E402

OUT = REPO / "evals/results/real-run-01/b3"
CK = OUT / "checkpoints"
SNAP = json.loads((REPO / "evals/results/real-mode/S4/result.json").read_text())["snapshot_id"]
PLANNER, SOLVER = "glm-5.3-flash", "glm-5.3"  # b3/inference-models.json, b3/inference-model-smoke.json
TUNNEL_PORT = 18000


def note(msg: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {msg}"
    print(line, flush=True)
    with open(OUT / "run.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")


def save(name: str, obj) -> None:
    (OUT / name).write_text(obj if isinstance(obj, str) else json.dumps(obj, indent=2),
                            encoding="utf-8")


def ssh_in(ip: str, cmd: str, data: bytes, timeout: int = 600) -> subprocess.CompletedProcess:
    return subprocess.run(["ssh", *ssh_opts(), f"ubuntu@{ip}", cmd], input=data,
                          capture_output=True, timeout=timeout)


def allowlisted_from(cp_ip: str, key: str) -> int:
    """HTTP status of an authenticated GET from bd-cp (header via stdin). /v2/account
    needs a valid key from an allowlisted IP; /v2/regions is public (always 200)."""
    p = ssh_in(cp_ip, "curl -s -o /dev/null -w '%{http_code}' -H @- https://api.vultr.com/v2/account",
               f"Authorization: Bearer {key}\n".encode(), timeout=60)
    try:
        return int(p.stdout.decode().strip() or 0)
    except ValueError:
        return 0


def wait_allowlist(cp_ip: str, rip: dict, key: str) -> None:
    status = allowlisted_from(cp_ip, key)
    note(f"allowlist check from bd-cp {cp_ip}: HTTP {status}")
    if status == 200:
        return
    (CK / "go-allowlist").unlink(missing_ok=True)
    save("checkpoints/bd-cp-ip.txt",
         f"reserved_ip_id={rip['id']}\nip={rip['subnet']}\n"
         f"ADD {rip['subnet']}/32 to the Vultr API access-control list, then create "
         f"{CK / 'go-allowlist'}\n")
    note(f"CHECKPOINT allowlist: add {rip['subnet']}/32 in the panel, then touch {CK / 'go-allowlist'}")
    t0 = time.monotonic()
    while time.monotonic() - t0 < 1800:
        if (CK / "go-allowlist").exists():
            status = allowlisted_from(cp_ip, key)
            note(f"go-allowlist seen; check from bd-cp: HTTP {status}")
            if status == 200:
                return
        time.sleep(15)
    raise RuntimeError("bd-cp's reserved IP never became allowlisted (30 min)")


def deploy_backend(cp_ip: str, cp_vpc_ip: str, subnet: str, env: dict) -> None:
    archive = subprocess.run(["git", "archive", "--format=tar", "HEAD", "backend", "contracts",
                              "forensics", "pyproject.toml"], cwd=REPO, capture_output=True,
                             check=True).stdout
    head = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True,
                          text=True, check=True).stdout.strip()
    r = ssh_in(cp_ip, "sudo mkdir -p /srv/bd && sudo chown ubuntu /srv/bd && tar -x -C /srv/bd", archive)
    if r.returncode != 0:
        raise RuntimeError(f"code upload failed: {r.stderr.decode()[-300:]}")
    note(f"backend code uploaded: git archive {head}")
    ssh(cp_ip, "command -v uv >/dev/null || (curl -LsSf https://astral.sh/uv/install.sh "
               "| sudo env UV_INSTALL_DIR=/usr/local/bin sh) >/dev/null 2>&1; uv --version")
    out = ssh(cp_ip, "cd /srv/bd/backend && uv sync --no-dev -q 2>&1 | tail -3; echo synced")
    note(f"uv sync on bd-cp: {out.strip()[-120:]}")
    lines = {
        "BD_REAL_MODE": "1", "VULTR_API_KEY": env["VULTR_API_KEY"],
        "VULTR_ISO_ID": env["VULTR_ISO_ID"], "BD_VPC_ID": env["BD_VPC_ID"],
        "BD_VPC_SUBNET": subnet, "CONTROL_URL": f"http://{cp_vpc_ip}:8000",
        "BD_OPERATOR_PASSWORD": env["BD_OPERATOR_PASSWORD"], "APP_SECRET": secrets.token_urlsafe(36),
        "VULTR_INFERENCE_KEY": env["VULTR_INFERENCE_KEY"],
        "BD_MODEL_PLANNER": PLANNER, "BD_MODEL_SOLVER": SOLVER,
        "BOOT_TIMEOUT_S": "1800",  # the out-of-band ESP swap happens inside this wait
        "DATABASE_URL": "sqlite:////srv/bd/b3.db",
    }
    body = "".join(f"{k}={v}\n" for k, v in lines.items()).encode()
    r = ssh_in(cp_ip, "umask 077 && cat > /srv/bd/b3.env", body)
    if r.returncode != 0:
        raise RuntimeError("writing the env file failed")
    # :8000 only from the VPC (twin) and loopback (operator tunnel)
    ssh(cp_ip, f"sudo iptables -I INPUT -p tcp --dport 8000 -j DROP && "
               f"sudo iptables -I INPUT -p tcp --dport 8000 -s {subnet} -j ACCEPT && "
               f"sudo iptables -I INPUT -p tcp --dport 8000 -i lo -j ACCEPT")
    ssh(cp_ip, "sudo systemd-run --unit bd-backend --uid ubuntu --working-directory /srv/bd/backend "
               "--property=EnvironmentFile=/srv/bd/b3.env /usr/local/bin/uv run --no-dev "
               "uvicorn backend.app:app --host 0.0.0.0 --port 8000")
    for _ in range(40):
        if "200" in ssh(cp_ip, "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/healthz",
                        check=False):
            note("backend up on bd-cp :8000")
            return
        time.sleep(5)
    raise RuntimeError("backend did not come up: " + ssh(
        cp_ip, "sudo journalctl -u bd-backend --no-pager | tail -20", check=False))


def find_twin(api: Api, case_thread: threading.Thread, timeout_s: float = 1800) -> dict | None:
    """The case's twin, or None once POST /cases has returned without one (failed early)."""
    t0 = time.monotonic()
    while time.monotonic() - t0 < timeout_s:
        if not case_thread.is_alive():
            return None
        for i in api.list_all("/v2/instances", "instances"):
            if (i.get("label") or "").startswith("bd-twin-"):
                return i
        time.sleep(15)
    raise TimeoutError("no bd-twin-* instance appeared")


def swap_when_post_attach_boot(api: Api, cp_ip: str, twin_id: str) -> bool:
    """The backend restores, then re-patches user_data and detaches + re-attaches the
    ISO (which reboots the clone). Only that boot has sr0 = BDFORENSICS; swap then."""
    vpc_ip = api.get(f"/v2/instances/{twin_id}/vpcs", name="b3-twin-vpcs")["vpcs"][0]["ip_address"]
    note(f"twin {twin_id} VPC IP {vpc_ip}: waiting for its post-ISO-attach boot")
    probe = "cat /proc/sys/kernel/random/boot_id; sudo blkid /dev/sr0 || true"
    t0, seen = time.monotonic(), None
    while time.monotonic() - t0 < 1800:
        p = s5_twin.clone_ssh(cp_ip, vpc_ip, probe, timeout=60)
        if p.returncode == 0 and 'LABEL="BDFORENSICS"' in p.stdout:
            boot = p.stdout.splitlines()[0]
            if seen == boot:
                note(f"clone in its post-attach boot ({boot[:8]}), sr0 labelled; ESP swap now")
                s5_twin.OUT = OUT
                return s5_twin.esp_swap(cp_ip, vpc_ip)
            seen = boot
            time.sleep(30)
            continue
        seen = None
        time.sleep(10)
    raise TimeoutError("clone never reached its post-attach boot")


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    CK.mkdir(parents=True, exist_ok=True)
    env = load_secrets()
    key = env["VULTR_API_KEY"]
    api = Api(key, evidence_dir=OUT / "api")
    vpc_id, subnet = env["BD_VPC_ID"], env["BD_VPC_SUBNET"]
    pub = subprocess.run(["ssh-keygen", "-y", "-f", str(SSH_KEY)], capture_output=True,
                         text=True, check=True).stdout.strip()
    cc = ("#cloud-config\nusers:\n  - name: ubuntu\n    groups: sudo\n    shell: /bin/bash\n"
          '    sudo: "ALL=(ALL) NOPASSWD:ALL"\n'
          f"    ssh_authorized_keys:\n      - {pub}\n")
    created: list[tuple[str, str]] = []
    findings: dict = {"snapshot_source": SNAP, "planner": PLANNER, "solver": SOLVER}
    tunnel = None
    case_snapshot = None
    try:
        # ---------------------------------------------------- reserved IP + bd-cp
        rip = None
        if env.get("BD_CP_RESERVED_IP_ID"):
            s, d = api.call("GET", f"/v2/reserved-ips/{env['BD_CP_RESERVED_IP_ID']}",
                            name="get-reserved-ip", ok=(404,))
            rip = d.get("reserved_ip") if s == 200 else None
        if rip is None:
            rip = api.call("POST", "/v2/reserved-ips",
                           {"region": REGION, "ip_type": "v4", "label": "bd-cp-ip"},
                           name="create-reserved-ip")[1]["reserved_ip"]
            set_secret("BD_CP_RESERVED_IP_ID", rip["id"])
        findings["reserved_ip"] = {"id": rip["id"], "ip": rip["subnet"]}
        save("checkpoints/bd-cp-ip.txt", f"reserved_ip_id={rip['id']}\nip={rip['subnet']}\n")
        note(f"reserved IP {rip['id']} = {rip['subnet']}")
        cp = api.call("POST", "/v2/instances", {
            "region": REGION, "plan": PLAN, "os_id": UBUNTU_2404, "label": "bd-cp", "hostname": "bd-cp",
            "tags": ["body-double"], "attach_vpc": [vpc_id], "backups": "disabled",
            "reserved_ipv4": rip["id"],
            "user_data": base64.b64encode(cc.encode()).decode()}, name="create-bd-cp")[1]["instance"]
        created.append(("instances", cp["id"]))
        cp, _ = api.wait(f"/v2/instances/{cp['id']}", "instance", "status", "active", 900, 10)
        cp_ip = cp["main_ip"]
        findings["bd_cp"] = {"id": cp["id"], "main_ip": cp_ip, "is_reserved_ip": cp_ip == rip["subnet"]}
        wait_ssh(cp_ip)
        cp_vpc = api.get(f"/v2/instances/{cp['id']}/vpcs", name="bd-cp-vpcs")["vpcs"][0]
        cp_vpc_ip = cp_vpc["ip_address"]
        if cp_vpc_ip not in ssh(cp_ip, "ip -4 -o addr"):  # Vultr VPC has no DHCP (S5)
            iface = ssh(cp_ip, f"ip -o link | grep -i {cp_vpc['mac_address']} | cut -d: -f2").strip()
            ssh(cp_ip, f"sudo ip link set {iface} up && sudo ip addr add "
                       f"{cp_vpc_ip}/{subnet.split('/')[1]} dev {iface}")
        findings["bd_cp"]["vpc_ip"] = cp_vpc_ip
        note(f"bd-cp {cp['id']} public {cp_ip} (reserved: {cp_ip == rip['subnet']}), VPC {cp_vpc_ip}")

        # shop-prod boots meanwhile (create from the S4 snapshot)
        shop = api.call("POST", "/v2/instances", {
            "region": REGION, "plan": PLAN, "snapshot_id": SNAP, "label": "bd-shop-prod",
            "hostname": "shop-prod", "tags": ["body-double"], "backups": "disabled"},
            name="create-shop-prod")[1]["instance"]
        created.append(("instances", shop["id"]))

        wait_allowlist(cp_ip, rip, key)
        deploy_backend(cp_ip, cp_vpc_ip, subnet, env)
        tunnel = subprocess.Popen(["ssh", *ssh_opts(), "-N", "-L",
                                   f"{TUNNEL_PORT}:127.0.0.1:8000", f"ubuntu@{cp_ip}"])
        time.sleep(5)
        base = f"http://127.0.0.1:{TUNNEL_PORT}"
        hz = httpx.get(f"{base}/healthz", timeout=30)
        save("healthz-before.json", {"status": hz.status_code, "body": hz.json()})
        note(f"healthz via tunnel: {hz.json()}")
        shop, _ = api.wait(f"/v2/instances/{shop['id']}", "instance", "status", "active", 900, 10)
        # a snapshot-created instance is 'active' while still restoring (server_status
        # locked/installingbooting): POST /v2/snapshots then 400s "server is locked" (run 3)
        shop, _ = api.wait(f"/v2/instances/{shop['id']}", "instance", "server_status", "ok", 1800, 15)
        findings["shop_prod"] = {"id": shop["id"], "main_ip": shop["main_ip"]}

        # ------------------------------------------------------------- the case
        client = httpx.Client(base_url=base, timeout=httpx.Timeout(30, read=5400))
        r = client.post("/auth/session", json={"operator": "operator",
                                               "password": env["BD_OPERATOR_PASSWORD"]})
        r.raise_for_status()
        client.headers["X-Human-Session"] = r.json()["session_token"]
        result: dict = {}

        def open_case() -> None:
            try:
                resp = client.post("/cases", json={"instance_id": shop["id"],
                                                   "reason": "Gate 2 B3: real case end-to-end"})
                result["status"], result["body"] = resp.status_code, resp.json()
            except Exception as exc:  # noqa: BLE001
                result["error"] = repr(exc)

        t_case = time.monotonic()
        th = threading.Thread(target=open_case, daemon=True)
        th.start()
        note(f"POST /cases for shop-prod {shop['id']} (runs the whole pipeline)")
        twin = find_twin(api, th)
        if twin is None:
            raise RuntimeError(f"POST /cases returned before any twin existed: {json.dumps(result)[:300]}")
        findings["twin_id"] = twin["id"]
        created.append(("instances", twin["id"]))  # teardown should delete it; finally double-checks
        findings["esp_swap_out_of_band"] = swap_when_post_attach_boot(api, cp_ip, twin["id"])
        note(f"ESP swap (driver, out-of-band): {findings['esp_swap_out_of_band']}")
        th.join(timeout=5400)
        findings["post_cases"] = {"status": result.get("status"), "error": result.get("error"),
                                  "seconds": round(time.monotonic() - t_case)}
        save("post-cases-response.json", result)
        case = (result.get("body") or {})
        case_id = case.get("id")
        note(f"POST /cases -> {result.get('status')} state={case.get('state')} "
             f"after {findings['post_cases']['seconds']}s")
        if not case_id:
            raise RuntimeError(f"no case from POST /cases: {json.dumps(result)[:300]}")
        detail = client.get(f"/cases/{case_id}").json()
        if detail["case"]["state"] != "closed":
            cr = client.post(f"/cases/{case_id}/close")
            save("close-response.json", {"status": cr.status_code, "body": cr.json()})
            detail = client.get(f"/cases/{case_id}").json()
        save("case-detail.json", detail)
        case_snapshot = detail["case"].get("snapshot_id")
        findings["case"] = {"id": case_id, "state": detail["case"]["state"],
                            "snapshot_id": case_snapshot, "seal": detail.get("seal"),
                            "steps": [{"tool": s["tool"], "exit_code": s["exit_code"]}
                                      for s in detail["steps"]]}

        # ------------------------------------------------- bundle + chain verify
        b = client.get(f"/cases/{case_id}/bundle")
        (OUT / f"bundle-{case_id}.zip").write_bytes(b.content)
        from contracts.hashing import verify_chain
        from contracts.models import LogEntry
        with zipfile.ZipFile(io.BytesIO(b.content)) as z:
            entries = [LogEntry.model_validate(e) for e in json.loads(z.read("case_log.json"))]
            names = z.namelist()
        bad = verify_chain(entries)
        findings["bundle"] = {"status": b.status_code, "files": names, "log_entries": len(entries),
                              "chain_first_bad_seq": bad, "verifies": bad is None}
        note(f"bundle: {b.status_code}, {len(entries)} log entries, chain verifies: {bad is None}")

        # --------------------------------------------- twin gone after close
        s, d = api.call("GET", f"/v2/instances/{twin['id']}", name="b3-twin-after-close", ok=(404,))
        findings["twin_get_after_close"] = s
        note(f"GET twin {twin['id']} after close -> {s}")
        hz = httpx.get(f"{base}/healthz", timeout=30)
        save("healthz-after.json", {"status": hz.status_code, "body": hz.json()})
        return 0
    finally:
        try:
            if "cp_ip" in locals():
                log = ssh(cp_ip, "sudo journalctl -u bd-backend --no-pager -o short-iso | tail -400",
                          check=False)
                save("backend-journal.txt", log)
        except Exception as exc:  # noqa: BLE001
            note(f"saving the backend journal failed: {exc}")
        if tunnel is not None:
            tunnel.terminate()
        for kind, rid in reversed(created):
            try:
                api.delete_until_gone(f"/v2/{kind}/{rid}", name=f"cleanup-{kind}")
            except Exception as exc:  # noqa: BLE001
                note(f"CLEANUP FAILED {kind} {rid}: {exc} -- run scripts/vultr_sweep.py")
        if case_snapshot:  # the case's own snapshot of shop-prod: not one of the kept ones
            try:
                api.delete_until_gone(f"/v2/snapshots/{case_snapshot}", name="cleanup-case-snapshot")
                findings["case_snapshot_deleted"] = case_snapshot
            except Exception as exc:  # noqa: BLE001
                note(f"CLEANUP FAILED case snapshot {case_snapshot}: {exc}")
        for fw in api.list_all("/v2/firewalls", "firewall_groups"):  # twin inbound-deny groups
            if (fw.get("description") or "").startswith("bd twin "):
                try:
                    api.delete_until_gone(f"/v2/firewalls/{fw['id']}", name="cleanup-twin-fw")
                except Exception as exc:  # noqa: BLE001
                    note(f"CLEANUP FAILED firewall {fw['id']}: {exc}")
        save("findings.json", findings)
        sw = subprocess.run([sys.executable, str(REPO / "scripts/vultr_sweep.py"), "--dry-run"],
                            capture_output=True, text=True, timeout=600)
        save("sweep-dry-run.txt", sw.stdout + sw.stderr)
        note("cleanup done; findings.json + sweep-dry-run.txt written")


if __name__ == "__main__":
    sys.exit(main())
