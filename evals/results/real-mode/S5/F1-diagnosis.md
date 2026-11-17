# F1: why the run-3 twin never registered

**Cause: (b) a real connectivity failure, not (a) a short window.** The ISO's
`bd-vpc-up` crashes, so the twin's VPC NIC never gets its address and every
packet to bd-cp (10.1.96.3) leaves through the public default route, where it
has no path. The ISO ships busybox `ip`, which rejects `-j`. `bd-vpc-up` calls
`ip -j -4 addr` and dies with `CalledProcessError`.

## (a) is ruled out: the twin had 27 minutes and sent nothing

Run-3 timeline (UTC), all from files in this folder:

| time | event | file |
|---|---|---|
| 06:52:23 | cp_stub listening on 10.1.96.3:8000 | `cp-log.jsonl` |
| 06:52:27 | twin `cfbd9590` created from the ISO | `008-T1b-create-from-iso.json` |
| 07:02:58 | 10 min later: no registration from the blank-disk ISO boot; restore starts | `011`/`012`/`013-T1b-*.json` |
| 07:07:21 | restore done (263 s), ISO still mounted | `050-T1b-after-restore.json`, `051-T1b-iso-after-restore.json` |
| 07:22:29 | 15 min more (`wait_register(..., 900)`): still no registration | `run.log` |
| 07:24:31 | twin deleted | `052-cleanup-instances.json` |

The "23 s" was only the gap from checkpoint 2 to cleanup. The twin ran the ISO
for 10 min before the restore and about 17 min after it. `cp-log.jsonl` holds
one line, `listening`. `scripts/cp_stub.py` logs every request it receives,
including rejected ones and 404s, so no TCP connection from either boot ever
reached bd-cp.

## (b) is reproduced locally with the identical ISO

- The ISO booted in run 3 has md5 `8990fab249357b10d961c87ebcd9f7ae`
  (`../S3/result.json`), the same bytes as the local `iso/out` build used here.
- `scripts/qemu_e2e_test.sh` gives that ISO a Vultr-shaped environment: a
  metadata service at 169.254.169.254 serving `/v1.json`, plus a VPC NIC with
  no DHCP and the control plane on it.
  `../../local-e2e/pre-fix/serial.log` shows:
  `Traceback ... File "/usr/bin/bd-vpc-up", line 22 ... subprocess.run(["ip", "-j", "-4", "addr"] ... CalledProcessError`
  then `bd: VPC interface not configured`.
- The metadata fetch, nft render, read-only mount, seal and jobs all worked
  (`../../local-e2e/pre-fix/md.jsonl`, `../../local-e2e/pre-fix/cp.jsonl`).
  The local register arrived only because QEMU's user-mode NAT routed it out
  the public NIC: `src_ip` is `10.1.96.3` (the NAT address), not the twin's
  `vpc_ip` 10.1.96.20. On Vultr that public-route path to a VPC address does
  not exist, which matches the empty `cp-log.jsonl`.
- `iso/out/manifest.txt` (the run-3 build) lists no iproute2 `ip` binary.

The other suspects are ruled out. Egress rules: the nft output chain allowed
cp:8000, and locally the same ruleset passed traffic. Inbound firewall: the
Vultr firewall group filters only the public NIC, and the twin connects
outbound. Jobs-server bind: cp_stub was listening on the VPC IP
(`cp-log.jsonl`), and ufw allowed the subnet (`scripts/s5_twin.py`).

**Fix:** add `iproute2` to the ISO's apk list (`iso/build.sh`). Rebuild, rerun
`qemu_e2e_test.sh` and require `src_ip == 10.1.96.20`. Then re-register the ISO
and rerun S5.
