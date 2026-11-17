# Real-mode findings (Vultr, Gate 1)

Answers from live Vultr runs (region ewr, plan vc2-1c-1gb). Each claim cites a
file under `evals/results/`. Paths are relative to `evals/results/real-mode/`
unless they start with `local-e2e/`.

## T1: can one create call boot the ISO with the snapshot's disk?

**No.** `POST /v2/instances` with both `snapshot_id` and `iso_id` returns
`400: please provide one app_id, image_id, iso_id, os_id, or snapshot_id`
(`S5/007-T1a-create-snapshot+iso.json`, `S5/findings.json` `t1a_create_status`).

**Fallback path, measured live:** create from `iso_id` alone (active in 15 s,
`S5/run8/findings.json` `t1b_iso_active_s`), then `POST .../restore` with the
snapshot (`S5/run8/*-T1b-restore.json`).

**But the fallback does not keep the ISO in charge (open problem).** After the
restore, the restored disk is bootable and Vultr boots it ahead of the
attached CD. This holds even after an explicit `POST .../iso/detach` plus
`POST .../iso/attach`, which the API reports as `isomounted`
(`S5/run8/*-T1b-iso-reattached.json`).
- In run 8, bd-cp found tcp/22 (sshd) open on the twin's VPC IP and no
  registration arrived in 15 min (`S5/run8/g3/post-restore-probe-from-bd-cp.txt`,
  `S5/run8/run.log`).
- In run 4 the console showed an Ubuntu login (`S5/checkpoints/console-2-take1.png`).

So **the restored clone's own OS runs**. That violates the PRD premise that
"the attacker's OS never runs" (header of `iso/rootfs/etc/bd/egress.nft`).
Until Vultr offers a CD-first boot order for a disk-bearing instance, the ISO
cannot investigate a restored snapshot in place. This needs a product
decision; it is not an infra fix.

Endpoint detail: ISO attach is `POST /v2/instances/{id}/iso/attach`.
`POST /v2/instances/{id}/iso` returns `405 Must be one of: GET`
(`S5/run7/047-T1b-iso-attach.json`).

## T2: how long do snapshot and restore take for a 25 GiB disk?

| operation | seconds | evidence |
|---|---|---|
| snapshot create -> complete | 507 | `S4/timings.json` |
| restore (run 2) | 234 | `S5/findings.json` at commit 9661f0f |
| restore (run 3) | 263 | `S5/findings.json` |
| restore (run 4) | 217 | `S5/run4/findings.json` |
| restore (run 7) | 198 | `S5/run7/findings.json` |
| restore (run 8) | 234 | `S5/run8/findings.json`, `S5/run8/run.log` |

The snapshot is 25 GiB (2.13 GB compressed): `S4/NOTES.md`.

## T3: do the investigation jobs run, and in which sandbox?

**Live:** not reached. The only post-restore boot that could run jobs booted
the clone, not the ISO (T1), so `results` is empty in `S5/run8/findings.json`.

**Local, same ISO, with no UART like Vultr:** all 3 jobs exit 0 from the VPC
IP 10.1.96.20, sealed (`local-e2e/kvm-noserial-fix-clone/cp.jsonl`):
- `os_facts`: hostname `shop-prod`, users root/ubuntu, packages cron, nginx,
  openssh-server, procps.
- `persistence_scan`: finds the planted `etc/cron.d/bdrv` per-minute backdoor.
- `detonate usr/local/bin/.bdrv`: runs under **`runtime=runsc (gVisor)`**,
  `network=none`, read-only rootfs. **gVisor is used; no runc fallback.**

## T4: does the twin register with the control plane over the VPC?

**Yes, live, for the ISO boot.** The blank-disk ISO boot registered from its
API-assigned VPC IP with egress sealed (all 5 internet probes timed out):
- run 7: `S5/run7/cp-log.jsonl` and `S5/run7/findings.json` `registrations`
  (src 10.1.96.4).
- run 8: `S5/run8/cp-log.jsonl`.
- run 6 also registered, 97 s after reboot (`S5/run6/NOTES.md`).

Getting there took three fixes, each found live:

1. **busybox `ip` has no `-j`.** `bd-vpc-up` crashed, so the VPC NIC never
   got its address (run 3). Fix: ship iproute2 in the ISO.
   Evidence: `S5/F1-diagnosis.md`, `local-e2e/pre-fix/serial.log`.
2. **The VPC only delivers to the IP Vultr assigns.** A self-chosen IP never
   answered ARP (`S5/run4/vpc-probe-from-bd-cp.txt`). Fix: read the twin's IP
   from `GET /v2/instances/{id}/vpcs` after create, PATCH it into user_data,
   then reboot (`S5/run5/010`-`012`).
3. **Vultr VMs have no UART.** `/dev/console` was `ttyS0`, so `boot.sh`
   (`set -e`) died on its first message, after the VPC IP was set but before
   the egress walls and the agent (run 5). Fix: `boot.sh` falls back to
   `tty0`. Evidence: `S5/run5/G1-diagnosis.md`,
   `S5/run5/g1/serial-probe-on-bd-cp.txt`, and the local reproduction
   `local-e2e/kvm-noserial-prefix/` vs `local-e2e/kvm-noserial-fix-blank/`.

The post-restore boot does not register, because it is not the ISO (T1).

## Console evidence

- Run 4, post-restore: `S5/checkpoints/console-2-take1.png` shows
  "Ubuntu 24.04.5 LTS - vultr login" (the clone booted).
  `console-2-take2.png` is a noVNC "Failed to connect" frame.
- Run 8, post-restore: RUN8_CONSOLE

## Operational findings

- **API reboot of an Ubuntu VM can lose SSH.** After `POST .../reboot`, SSH
  did not come back in 10 min; a guest `systemctl reboot` worked in 52 s
  (`S4/NOTES.md`, attempts 2 and 3). On the ISO twin the API reboot is a real
  reset (37 s outage, `S5/run5/g1/ping-from-bd-cp.log`).
- **Metadata:** `/v1/user-data` is 403/404 on live Vultr. The working endpoint
  is `GET /v1.json` with `Metadata-Token: cloudinit` (`S5/NOTES.md`).
- **The API key allowlist pins one machine IP.** On 2026-11-16, calls from
  another IP got 401 on ISO, object-storage, snapshot and VPC endpoints, while
  `/v2/instances` still returned 200. *No API response was saved at the time,
  so this claim has no evidence file.* `S3/result.json` is the ISO
  registration that succeeded once the IP was allowed.
- **Account ISO quota.** Registering a third ISO failed with "Please delete some
  existing ISOs before adding new ones". The obsolete run-3 ISO was deleted to
  make room (`S3/g3-iso-quota/001-delete-obsolete-run3-iso.json`).
- **A killed driver leaks resources and logs.** Run 6's driver was killed by
  the host (memory), so its `finally` never ran. The twin was then locked by
  the restore (409) and was deleted 4 min later (`S5/run6/NOTES.md`,
  `S5/run6/killed-cleanup/`). Long runs are now launched detached
  (`Start-Process`), and `finally` saves bd-cp's log before deleting it.
- **herdr workers need `hc run --keep`.** Run 5's driver died with its
  herdr-core session while its instances kept running: `S5/run5/run.log`
  stops at the reboot line, and the two instances were still live 25 min later
  (`S5/run5/g1/001-g1-twin-before-reboot.json`).
