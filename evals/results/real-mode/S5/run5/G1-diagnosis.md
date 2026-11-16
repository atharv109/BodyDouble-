# G1: why the run-5 twin never registered

**Cause: Vultr VMs have no serial port, and the ISO points `/dev/console` at
`ttyS0`. In `boot.sh` (`set -eu`), the first console write fails with EIO.
That write is `bd-vpc-up`'s success line. Its `|| echo` fallback fails the
same way, so `set -e` kills `boot.sh` right after the VPC IP is set. The nft
walls never load and the twin agent never starts.**

The three candidates in TASK-FINISH-3 are all ruled out (see the end). This
cause was not on the list.

## What the live twin did (4199e9ad, VPC 10.1.96.4)

| observation | meaning | evidence |
|---|---|---|
| stub log has only `listening`; it logs every request, 404s and 401s included | no TCP connection ever reached bd-cp | `g1/cp-log-after-reboot.jsonl` (1 line) |
| bd-cp pings 10.1.96.4 from the twin's VPC MAC `5a:00:07:0e:a8:31` | the VPC IP is configured on the twin | `g1/vpc-dhcp-and-rst-probe.txt`, `010-T1b-twin-vpcs.json` |
| the VPC answers no DHCP (busybox `udhcpc` from bd-cp: `no lease`) | only `bd-vpc-up` can set that IP, so the user_data bootstrap was valid and `bd-vpc-up` ran | `g1/vpc-dhcp-and-rst-probe.txt` |
| a SYN to a closed port on 10.1.96.4 gets **RST** from that MAC; ICMP echo is answered | `egress.nft` (input `policy drop`) is **not loaded** | `g1/vpc-dhcp-and-rst-probe.txt` |
| 0 TCP packets from the twin in 75 s, and again in 8 min after a reboot | the agent never ran | `g1/tcpdump-from-bd-cp.txt` |
| an API reboot (`g1/003-g1-twin-reboot.json`) brings the same state back in 37 s | deterministic, not a reboot race | `g1/ping-from-bd-cp.log` (seq 7-55 lost, then answered) |

In `iso/rootfs/etc/bd/boot.sh`, the only code between "VPC IP set" and
"walls loaded" is `bd-vpc-up ... || echo ... >&2` followed by `nft -f`. The
twin stopped inside that window.

## Why: no UART on Vultr

- `iso/boot/isolinux.cfg`: `APPEND console=tty0 console=ttyS0,115200`. The
  last `console=` becomes `/dev/console`, so busybox init gives `boot.sh`
  its stdio on `ttyS0`.
- On Vultr hardware (bd-cp, same plan and region), `/proc/tty/driver/serial`
  shows `uart:unknown` for every port, and writing to `/dev/ttyS0` fails (rc=1):
  `g1/serial-probe-on-bd-cp.txt`. Vultr's own Ubuntu boots with `console=tty0`
  last.
- `bd-vpc-up` runs `ip addr add` first and then `print(...)`. Python hits EIO,
  so it exits non-zero after the IP is already set. The `|| echo ... >&2`
  fallback writes to the same dead console and fails too, so `set -e` aborts
  `boot.sh` before `nft -f`.
- In QEMU there is always a UART (`-serial file:`), so every local run passed.

## Local proof (same ISO: md5 fd0b20cb..., identical to Vultr ISO c84d165a)

| local run (`scripts/qemu_e2e_test.sh` in WSL2) | UART | result | evidence |
|---|---|---|---|
| KVM `-cpu host`, blank disk | yes | registered (unsealed: no clone) | `../../../local-e2e/kvm-blank/cp.jsonl` |
| KVM `-cpu host`, blank disk, `NO_SERIAL=1` | **none** | metadata fetched, **never registers**, same as Vultr | `../../../local-e2e/kvm-noserial-prefix/md.jsonl`, `cp.jsonl` |

The first row rules out KVM/CPU features and the blank disk. Removing the UART
alone flips the outcome.

## Candidates from the task, ruled out

- *nft rules block VPC traffic:* the rules are not loaded at all (RST above).
- *bootstrap/metadata fetch fails on the new ISO:* the VPC IP from the bootstrap
  is configured, and locally the md fetch works with the same ISO.
- *reboot not applied:* the API reboot really resets the VM (37 s outage), and
  the clean boot fails the same way.

The same mechanism also explains run 3: there `bd-vpc-up` crashed (busybox
`ip -j`, `../F1-diagnosis.md`), and its traceback plus the fallback echo hit
the dead console, so that boot also died before the walls.

Fix (G2): `boot.sh` checks its console first and falls back to `tty0` (the VNC
screen the orchestrator photographs) when it is dead, so no message can kill
the boot.
