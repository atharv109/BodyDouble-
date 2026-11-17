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
import hashlib
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


# The ESP swap (runs 8-10): the restored, bootable disk beats the attached CD
# (run8/g3/post-restore-probe-from-bd-cp.txt), and the clone's own GRUB menu never
# auto-boots a one-shot entry: runs 9 and 10 sat at the menu with bd-iso selected,
# even with timeout=3 and recordfail unset (run9|run10/checkpoints/*.png). So the
# clone's UEFI loaders are replaced by a standalone GRUB EFI binary that boots the
# ISO's kernel at once (scripts/build_oneshot_efi.sh). The kernel and initramfs are
# copied onto the ESP (/bd/): Vultr's firmware does not expose the CD, so GRUB
# could not load them from it (run 11: 'grub>', run11/checkpoints/). Originals are
# kept as *.bd-orig. Caveat: the clone's own OS runs once, unsealed, to make the swap.
ONESHOT_EFI = REPO / "iso" / "out" / "bd-oneshot-x64.efi"
ONESHOT_DIR = REPO / "iso" / "out" / "bd-oneshot"
ESP_LOADERS = ["/boot/efi/EFI/BOOT/BOOTX64.EFI", "/boot/efi/EFI/ubuntu/shimx64.efi",
               "/boot/efi/EFI/ubuntu/grubx64.efi"]


def clone_ssh(cp_ip: str, vpc_ip: str, cmd: str, timeout: int = 120,
              data: bytes | None = None) -> subprocess.CompletedProcess:
    """SSH into the restored clone over the VPC, jumping through bd-cp."""
    jump = " ".join(["ssh", *ssh_opts(), "-W", "%h:%p", f"ubuntu@{cp_ip}"])
    p = subprocess.run(["ssh", *ssh_opts(), "-o", f"ProxyCommand={jump}", f"ubuntu@{vpc_ip}", cmd],
                       capture_output=True, timeout=timeout, input=data)
    return subprocess.CompletedProcess(p.args, p.returncode, p.stdout.decode(errors="replace"),
                                       p.stderr.decode(errors="replace"))


def esp_swap(cp_ip: str, vpc_ip: str) -> bool:
    """Make the clone's next boot the ISO: replace its UEFI loaders with the one-shot
    EFI binary, then reboot. Evidence (every command's output) -> OUT/esp-swap.txt."""
    log = OUT / "esp-swap.txt"
    t0 = time.monotonic()
    while True:  # the clone boots by itself after the restore
        p = clone_ssh(cp_ip, vpc_ip, "uname -a; uptime")
        if p.returncode == 0 or time.monotonic() - t0 > 600:
            break
        time.sleep(15)
    swap = "; ".join(f"if [ -f {f} ]; then sudo cp -n {f} {f}.bd-orig && sudo cp /tmp/bd.efi {f}; fi"
                     for f in ESP_LOADERS)
    steps = [
        ("lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT; ls -d /sys/firmware/efi", None),
        # the ISO kernel needs the media in the drive (run 12): wait up to 3 min for it
        ("for i in $(seq 36); do sudo blkid /dev/sr0 | grep -q 'LABEL=\"BDFORENSICS\"' && break; "
         "sleep 5; done; lsblk -o NAME,SIZE /dev/sr0; sudo blkid /dev/sr0 | grep BDFORENSICS", None),
        ("sudo efibootmgr -v 2>&1 || true; sudo find /boot/efi -type f -iname '*.efi' -ls", None),
        ("cat > /tmp/bd.efi && sha256sum /tmp/bd.efi", ONESHOT_EFI.read_bytes()),
        *((f"sudo mkdir -p /boot/efi/bd && sudo tee /boot/efi/bd/{n} >/dev/null && "
           f"sudo sha256sum /boot/efi/bd/{n}", (ONESHOT_DIR / n).read_bytes())
          for n in ("vmlinuz-lts", "initramfs-bd")),
        ("sudo mkdir -p /boot/efi/EFI/BOOT; [ -f /boot/efi/EFI/BOOT/BOOTX64.EFI ] || "
         "sudo cp /tmp/bd.efi /boot/efi/EFI/BOOT/BOOTX64.EFI; " + swap
         + "; sync; sudo sha256sum /boot/efi/EFI/*/*.efi", None),
    ]
    ok = p.returncode == 0
    with open(log, "w", encoding="utf-8") as f:
        f.write(f"$ wait for clone sshd: rc={p.returncode} after {time.monotonic() - t0:.0f}s\n"
                f"{p.stdout}{p.stderr}\n")
        f.write(f"one-shot EFI: {ONESHOT_EFI.name} sha256 "
                f"{hashlib.sha256(ONESHOT_EFI.read_bytes()).hexdigest()}\n\n")
        for cmd, data in steps if ok else []:
            r = clone_ssh(cp_ip, vpc_ip, cmd, data=data)
            f.write(f"$ {cmd[:200]}\nrc={r.returncode}\n{r.stdout}{r.stderr}\n")
            ok = ok and r.returncode == 0
        if ok:
            r = clone_ssh(cp_ip, vpc_ip, "sudo systemd-run --on-active=2 systemctl reboot", timeout=60)
            f.write(f"$ reboot in 2 s\nrc={r.returncode}\n{r.stdout}{r.stderr}\n")
            ok = r.returncode == 0
    return ok


def iso_state(api: Api, tid: str, name: str) -> str:
    return api.call("GET", f"/v2/instances/{tid}/iso", name=name)[1]["iso_status"].get("state", "")


# W1 (Gate 2): measure egress in the pre-swap window itself. The restored clone
# is briefly Ubuntu with its public interface (real-mode finding: "the clone's
# own OS runs once, unsealed"); these probes run from inside it BEFORE the
# ESP swap modifies the loaders. Contrast: run 13 measured 5/5 egress blocked
# AFTER the seal — this is the other end of the timeline.
def preswap_probes(cp_ip: str, vpc_ip: str, out_dir: Path, listener: str | None) -> bool:
    """From the restored clone: timestamped outbound probes (HTTPS 443, HTTP 80,
    DNS 53, ICMP), each recorded with start / result / end timestamps, plus 3 to
    the W1 listener outside Vultr (scripts/w1_listener.py; `listener` is its
    http://IP:PORT/w1/<nonce> URL). Then a background loop on the clone keeps
    probing the listener every ~2 s until the ESP-swap reboot kills it, so the
    listener's log pins the end of the unsealed window from outside Vultr.
    Each listener probe carries the clone's send time and /proc/uptime.
    Evidence: <out_dir>/probe.txt. Returns True when the probes ran."""
    t0 = time.monotonic()
    first = "uname -a; uptime -s; cat /proc/uptime; ip -4 -brief addr show"
    p = clone_ssh(cp_ip, vpc_ip, first)
    while p.returncode != 0 and time.monotonic() - t0 < 600:
        # the ISO detach/attach reboots the clone (W1 try 1: 'up 0 min' at the
        # swap, run-01-w1/esp-swap.txt): wait for its sshd
        time.sleep(10)
        p = clone_ssh(cp_ip, vpc_ip, first)
    reachable = p.returncode == 0
    lst = []
    if listener:
        lst = [line for i in (1, 2, 3) for line in (
            f'ts=$(date -u +%FT%T.%NZ); up=$(cut -d" " -f1 /proc/uptime); echo "$ts START listener fg{i} up=$up"',
            f"curl -sS -m 5 -w ' http=%{{http_code}}\n' \"{listener}/fg{i}?sent=$ts&up=$up\"",
            f'rc=$?; echo "$(date -u +%FT%T.%NZ) END listener fg{i} rc=$rc"')]
    cmd = "\n".join([
        'echo "== preswap egress probes: start $(date -u +%FT%T.%NZ) =="',
        'echo "iface:"; ip -4 -brief addr show',
        *lst,
        'echo "$(date -u +%FT%T.%NZ) START https443"',
        "curl -sS -m 8 -w '\\nRC https443 http=%{http_code} t=%{time_total}s\\n' https://api.ipify.org",
        'rc=$?; echo "$(date -u +%FT%T.%NZ) END https443 rc=$rc"',
        'echo "$(date -u +%FT%T.%NZ) START http80"',
        "curl -sS -m 8 -w '\\nRC http80 http=%{http_code} t=%{time_total}s\\n' 'http://ip-api.com/line/?fields=query'",
        'rc=$?; echo "$(date -u +%FT%T.%NZ) END http80 rc=$rc"',
        'echo "$(date -u +%FT%T.%NZ) START dns53"',
        "getent hosts example.com",
        'rc=$?; echo "$(date -u +%FT%T.%NZ) END dns53 rc=$rc"',
        'echo "$(date -u +%FT%T.%NZ) START icmp"',
        "ping -c 1 -W 3 8.8.8.8 2>&1 | tail -2",
        'rc=$?; echo "$(date -u +%FT%T.%NZ) END icmp rc=$rc"',
        'echo "== preswap egress probes: end $(date -u +%FT%T.%NZ) =="',
    ])
    r = clone_ssh(cp_ip, vpc_ip, cmd, timeout=240)
    bg = None
    if listener and reachable:
        loop = ("i=0\nwhile [ $i -lt 450 ]; do i=$((i+1))\n"
                '  ts=$(date -u +%FT%T.%NZ); up=$(cut -d" " -f1 /proc/uptime)\n'
                f'  curl -s -m 2 -o /dev/null "{listener}/bg$i?sent=$ts&up=$up"\n'
                "  sleep 2\ndone\n")
        bg = clone_ssh(cp_ip, vpc_ip, "cat > /tmp/bd-w1-loop.sh && sudo systemd-run "
                       "--unit bd-w1-loop --collect /bin/sh /tmp/bd-w1-loop.sh",
                       data=loop.encode())
    took = time.monotonic() - t0
    with open(out_dir / "probe.txt", "w", encoding="utf-8") as f:
        f.write("W1 pre-swap egress probes - from the restored clone (the clone's own "
                "OS, unsealed, public interface) BEFORE the ESP swap.\n")
        f.write(f"clone sshd rc={p.returncode}; probe ssh rc={r.returncode}; window +{took:.0f}s\n\n")
        f.write(f"$ clone uname / boot time (uptime -s) / /proc/uptime / ifaces\n{p.stdout}{p.stderr}\n")
        f.write(f"$ probes\n{r.stdout}{r.stderr}\n")
        if bg is not None:
            f.write(f"$ background listener loop (until the swap reboot): rc={bg.returncode}\n"
                    f"{bg.stdout}{bg.stderr}\n")
    with open(out_dir / "probe.rc.json", "w", encoding="utf-8") as f:
        f.write(json.dumps({"clone_ssh_rc": p.returncode, "probe_rc": r.returncode,
                            "bg_loop_rc": None if bg is None else bg.returncode,
                            "window_s": round(took)}, indent=2))
    return reachable and r.returncode == 0


def append_listener_capture(out_dir: Path, listener_log: Path, t_swap_reboot: str) -> int:
    """After the swap: append the listener-side capture (probe lines only) to
    probe.txt, next to the driver's own time for the swap's reboot command.
    Returns the number of probes the listener received."""
    lines = []
    if listener_log.is_file():
        for raw in listener_log.read_text(encoding="utf-8").splitlines():
            e = json.loads(raw)
            if e.get("probe"):
                lines.append(f"{e['recv_utc']}  from {e['src_ip']}:{e['src_port']}  {e['path']}")
    with open(out_dir / "probe.txt", "a", encoding="utf-8") as f:
        f.write(f"\n$ listener-side capture ({listener_log.name}, operator machine, outside Vultr): "
                f"{len(lines)} probes\n")
        f.write(f"driver: swap reboot command sent at {t_swap_reboot} (UTC)\n")
        f.write("\n".join(lines) + "\n")
        f.write("\nVERDICT: to be completed by the worker from the results above.\n")
    return len(lines)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--batch", default="", help="evidence subfolder of S5/ (fresh numbering), e.g. run4")
    ap.add_argument("--checkpoint-dir", type=Path, default=None, help="default: S5/checkpoints")
    ap.add_argument("--checkpoint-wait", type=float, default=1200)
    ap.add_argument("--preswap-probe-dir", type=Path, default=None,
                    help="W1: run outbound probes from the restored clone before "
                         "the ESP swap; write probe.txt under this directory")
    ap.add_argument("--w1-listener-url", default=None,
                    help="W1: http://IP:PORT/w1/<nonce> of scripts/w1_listener.py (outside Vultr)")
    ap.add_argument("--w1-listener-log", type=Path, default=None,
                    help="W1: that listener's --log file, merged into probe.txt after the swap")
    ap.add_argument("--skip-t1a", action="store_true")
    args = ap.parse_args()
    if not (ONESHOT_EFI.is_file() and (ONESHOT_DIR / "initramfs-bd").is_file()):  # before any spend
        sys.exit(f"missing {ONESHOT_EFI}: run scripts/build_oneshot_efi.sh")
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
        if args.w1_listener_url:  # W1: is the listener reachable from inside Vultr at all?
            st = subprocess.run(["ssh", *ssh_opts(), f"ubuntu@{cp_ip}",
                                 f"curl -sS -m 8 '{args.w1_listener_url}/selftest-from-bd-cp'"],
                                capture_output=True, text=True, timeout=60)
            findings["w1_listener_reachable_from_vultr"] = st.returncode == 0 and "bd-w1 ok" in st.stdout
            note(f"W1 listener self-test from bd-cp: rc={st.returncode} {st.stdout.strip()[:80]!r} "
                 f"{st.stderr.strip()[:120]!r}")
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
        # The restore empties the CD drive while the API still says "isomounted": the
        # clone saw sr0 at 1024M (empty) vs the 376 MiB ISO (run9/grub-one-shot.txt,
        # run12/esp-swap.txt), so the ISO kernel found no media (run 12). Re-insert it:
        # detach + attach. attach is POST /iso/attach (POST /iso -> 405, run7/047).
        api.call("POST", f"/v2/instances/{tid}/iso/detach", name="T1b-iso-detach")
        for _ in range(40):
            if iso_state(api, tid, "T1b-iso-after-detach") != "isomounted":
                break
            time.sleep(15)
        api.call("POST", f"/v2/instances/{tid}/iso/attach", {"iso_id": iso_id}, name="T1b-iso-attach")
        for _ in range(40):
            if iso_state(api, tid, "T1b-iso-after-attach") == "isomounted":
                break
            time.sleep(15)
        findings["t1b_iso_mounted_after_restore"] = iso_state(api, tid, "T1b-iso-mounted") == "isomounted"
        # W1: the clone is about to be Ubuntu with its public interface — measure
        # egress NOW, before the ESP swap (evals/results/real-run-01/preswap-egress/)
        if args.preswap_probe_dir:
            args.preswap_probe_dir.mkdir(parents=True, exist_ok=True)
            findings["preswap_probes_ran"] = preswap_probes(cp_ip, ip_b, args.preswap_probe_dir,
                                                            args.w1_listener_url)
            note(f"W1 pre-swap probes: ran={findings['preswap_probes_ran']} -> {args.preswap_probe_dir}")
        # the restored disk beats the CD (runs 4, 8): swap the clone's UEFI loaders
        findings["t1b_esp_swap"] = esp_swap(cp_ip, ip_b)
        t_swap_reboot = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        note(f"T1b twin {tid}: restore {findings['t2_restore_s']}s; ESP swap to the ISO: "
             f"{findings['t1b_esp_swap']}; waiting for the post-restore registration")
        regs = wait_register(cp_ip, n_before + 1, 900)
        if args.preswap_probe_dir and args.w1_listener_log:  # the window is over: merge
            findings["w1_listener_probes"] = append_listener_capture(
                args.preswap_probe_dir, args.w1_listener_log, t_swap_reboot)
        findings["t1b_after_restore_registered"] = len(regs) > n_before
        if len(regs) > n_before:
            findings["t2_restore_to_register_s"] = round(time.monotonic() - t_restore)
        note(f"T1b twin {tid}: restore {findings['t2_restore_s']}s, ISO registered after restore: "
             f"{findings['t1b_after_restore_registered']}")
        # checkpoint as soon as the ISO is up; the agent keeps running jobs meanwhile
        findings["checkpoint_2_go"] = checkpoint(
            2, "Alpine ISO console on tty0 (not Ubuntu login) with boot.sh lines: 'bd: no serial "
               "console; boot messages on tty0', 'bd-vpc-up: <vpc_ip>/20 on "
               "eth1', 'bd: cloned disk /dev/vda1 mounted inert and read-only at /mnt/disk', "
               "'bd: sandbox image loaded; runtimes: ...runsc...'",
            args.checkpoint_dir, args.checkpoint_wait, twin_id=tid)
        res = wait_results(cp_ip, len(JOBS), 900)  # the agent runs the 3 queued jobs
        findings["t3_results_received"] = len(res)
        note(f"T3: {len(res)}/{len(JOBS)} job results received")
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
            try:  # retries network blips (run 4) and 409 'locked' (W2 leaked fb0dd8a4)
                api.delete_until_gone(f"/v2/{kind}/{rid}", name=f"cleanup-{kind}")
            except Exception as exc:  # keep cleaning the rest
                note(f"CLEANUP FAILED {kind} {rid}: {exc} -- run scripts/vultr_sweep.py")
        time.sleep(20)
        for kind, rid in created:
            if kind == "firewalls":  # firewall deletes fail while instances still hold it
                api.call("DELETE", f"/v2/{kind}/{rid}", name="cleanup-fw-retry", ok=(404, 400, 409, 412))
        (OUT / "findings.json").write_text(json.dumps(findings, indent=2))
        note("cleanup done; findings.json written")


if __name__ == "__main__":
    sys.exit(main())
