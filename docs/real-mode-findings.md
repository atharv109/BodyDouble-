# Real-mode findings (Vultr, Gate 1)

Answers from live Vultr runs (region ewr, plan vc2-1c-1gb). Each claim cites a
file under `evals/results/`. Paths are relative to `evals/results/real-mode/`
unless they start with `local-e2e/`.

**Result:** the full T1b flow passes live in run 13.
1. Create the twin from the ISO, then register over the VPC.
2. Restore the snapshot, then re-insert the ISO and swap the clone's ESP loaders.
3. The ISO boots with the clone mounted read-only and registers sealed.
4. The twin runs 3 jobs, including detonate under gVisor, and returns their
   results.

Evidence: `S5/run13/findings.json` (`t1b_after_restore_registered: true`,
`t3_results_received: 3`) and `S5/run13/cp-log.jsonl`.

## T1: can one create call boot the ISO with the snapshot's disk?

**No.** `POST /v2/instances` with both `snapshot_id` and `iso_id` returns
`400: please provide one app_id, image_id, iso_id, os_id, or snapshot_id`
(`S5/007-T1a-create-snapshot+iso.json`, `S5/findings.json` `t1a_create_status`).

**The working fallback (run 13)** has five steps. Each one exists because of a
failure in an earlier run.

1. **Create the twin from `iso_id` alone.** It is active in 15 s
   (`S5/run13/findings.json` `t1b_iso_active_s`). Then write the API-assigned
   VPC IP into `user_data` and reboot. The blank-disk ISO boot registers (T4).
2. **`POST .../restore` with the snapshot** (`S5/run13/015-T1b-restore.json`).
3. **Re-insert the ISO** with `POST .../iso/detach` then
   `POST .../iso/attach` (`S5/run13/051`-`056`).
   - The restore empties the CD drive while the API still reports
     `isomounted`. The restored clone saw `sr0` as 1024M (empty) instead of
     the 376 MiB ISO (`S5/run9/grub-one-shot.txt`, `S5/run12/esp-swap.txt`).
   - After the re-insert, the clone saw `sr0 376M LABEL="BDFORENSICS"`
     (`S5/run13/esp-swap.txt`).
   - Endpoint detail: attach is `POST /v2/instances/{id}/iso/attach`.
     `POST /v2/instances/{id}/iso` returns `405 Must be one of: GET`
     (`S5/run7/047-T1b-iso-attach.json`).
4. **ESP swap.** The restored disk boots ahead of the CD (see below), so
   bd-cp SSHes into the clone over the VPC and makes three changes:
   - Copies the ISO's own kernel and initramfs to the clone's ESP (`/bd/`).
   - Replaces the clone's UEFI loaders (`\EFI\ubuntu\shimx64.efi`,
     `grubx64.efi`, `\EFI\BOOT\BOOTX64.EFI`) with a standalone GRUB EFI binary
     whose embedded config boots that kernel at once
     (`scripts/build_oneshot_efi.sh`).
   - Keeps the originals as `*.bd-orig`.

   Evidence: `S5/run13/esp-swap.txt`, which records the sha256 of every file
   it copies.
5. **Reboot.** The firmware runs the swapped loader. The ISO kernel boots,
   its initramfs finds the CD with its own drivers, and the twin registers
   sealed.

**Why each piece is needed:**

| run | what we tried | what happened | evidence |
|---|---|---|---|
| 4, 8 | restore, then detach + re-attach the ISO | the restored Ubuntu disk boots, not the CD: Ubuntu login on the console, sshd open on the VPC IP | `S5/checkpoints/console-2-take1.png`, `S5/run8/g3/post-restore-probe-from-bd-cp.txt` |
| 9, 10 | GRUB one-shot inside the clone (`grub-reboot` to a custom entry, then `timeout=3` and `recordfail` unset) | the clone's GRUB menu sits with `bd-iso` selected and never boots it | `S5/run9/checkpoints/console-2-take2.png`, `S5/run10/checkpoints/console-2-take2.png`, `S5/run10/grub-one-shot.txt` |
| 11 | ESP swap, kernel loaded from the CD by label | GRUB drops to `grub>`. Vultr's UEFI firmware does not expose the SATA CD: there is no DVD-ROM boot option in `efibootmgr` | `S5/run11/checkpoints/console-2-take1.png`, `S5/run11/esp-swap.txt` |
| 12 | ESP swap, kernel on the ESP | GRUB loads the kernel (`root=hd0,gpt1`, `EFI stub: Loaded initrd`), but the drive is empty after the restore, so the initramfs finds no media | `S5/run12/checkpoints/console-2-take1.png`, `S5/run12/esp-swap.txt` |
| 13 | + detach/attach to re-insert the ISO | **registers sealed; 3/3 results** | `S5/run13/` |

Each step was first reproduced or verified locally under OVMF UEFI:
`local-e2e/kvm-uefi-esp-grub/`, `local-e2e/kvm-uefi-esp-oneshot-efi/` and
`local-e2e/kvm-uefi-esp-kernel-on-esp/`. The `kernel-on-esp` run first failed
because the GRUB image did not autoload its partition and FAT drivers.

**Caveats:**
- **The clone's own OS runs once, unsealed, before the ISO.** The restored
  disk boots Ubuntu first, and the swap needs it running to accept the SSH
  connection.
  - In run 13 the clone was up 39 s or less after the restore, with sshd
    reachable on the VPC (`S5/run13/esp-swap.txt`; the same in runs 11 and 12).
  - It had its public interface during that window. The PRD premise that
    "the attacker's OS never runs" (header of `iso/rootfs/etc/bd/egress.nft`)
    therefore holds only after the swap.
  - The SSH login uses the snapshot's cloud-init key, which only works on our
    own demo snapshot.
- **The swap modifies the clone's ESP.** The original loaders are kept as
  `*.bd-orig` but are not restored automatically. After the investigation the
  twin is deleted (or restored again from the snapshot), so the original
  snapshot is never touched.
- **Under UEFI the console shows no `boot.sh` lines.** The Alpine kernel has
  no EFI framebuffer driver, so the screen stays on the GRUB/EFI-stub frame
  (`S5/run13/checkpoints/console-2-take1.png`). The proof of the sealed boot is
  the registration's `seal` block in `S5/run13/cp-log.jsonl`.

## T2: how long do snapshot and restore take for a 25 GiB disk?

| operation | seconds | evidence |
|---|---|---|
| snapshot create -> complete | 507 | `S4/timings.json` |
| restore (run 2) | 234 | `S5/findings.json` at commit 9661f0f |
| restore (run 3) | 263 | `S5/findings.json` |
| restore (run 4) | 217 | `S5/run4/findings.json` |
| restore (run 7) | 198 | `S5/run7/findings.json` |
| restore (runs 8-12) | 234, 251, 217, 188, 187 | `S5/run8`-`run12/run.log` |
| restore (run 13) | 233 | `S5/run13/findings.json` `t2_restore_s` |
| restore start -> sealed ISO registered (run 13) | 364 | `S5/run13/findings.json` `t2_restore_to_register_s` |

The snapshot is 25 GiB (2.13 GB compressed): `S4/NOTES.md`.

## T3: do the investigation jobs run, and in which sandbox?

**Yes, live (run 13).** All 3 jobs ran on the sealed twin against the
read-only clone and returned exit 0 (`S5/run13/cp-log.jsonl`,
`S5/run13/findings.json` `results`):
- `os_facts`: the clone is "Ubuntu 24.04.5 LTS".
- `persistence_scan`: lists the clone's cron and other persistence locations.
- `detonate`: runs under **`runtime=runsc (gVisor)`**, `network=none`,
  read-only rootfs, 1 CPU, 512 MB, 128 pids. **gVisor is used; there is no
  runc fallback.**

The same 3 jobs pass locally on the planted demo victim. `persistence_scan`
finds the planted `etc/cron.d/bdrv` backdoor, which the live S4 snapshot does
not contain (`local-e2e/kvm-noserial-fix-clone/cp.jsonl`,
`local-e2e/kvm-uefi-esp-kernel-on-esp/cp.jsonl`).

## T4: does the twin register with the control plane over the VPC?

**Yes, live, before and after the restore.** Run 13 has two registrations from
the API-assigned VPC IP 10.1.96.4 (`S5/run13/cp-log.jsonl`):
- **Blank-disk ISO boot:** `egress_blocked: true`; `disk_read_only: false`
  because there is no clone yet.
- **Post-restore ISO boot:** `disk_read_only: true` (`/dev/vda2 on /mnt/disk:
  ro,nosuid,nodev,noexec`) and `egress_blocked: true` (all 5 internet probes
  timed out).

The blank-disk registration also passed in runs 6-12 (`S5/run6/NOTES.md`,
`S5/run7`-`run12/run.log`).

Before T1b's boot-order work, three fixes were needed. Each was found live:

1. **busybox `ip` has no `-j`.** `bd-vpc-up` crashed, so the VPC NIC never
   got its address (run 3). Fix: ship iproute2 in the ISO.
   Evidence: `S5/F1-diagnosis.md`, `local-e2e/pre-fix/serial.log`.
2. **The VPC only delivers to the IP Vultr assigns.** A self-chosen IP never
   answered ARP (`S5/run4/vpc-probe-from-bd-cp.txt`). Fix: read the twin's IP
   from `GET /v2/instances/{id}/vpcs` after create, PATCH it into `user_data`,
   then reboot (`S5/run5/010`-`012`).
3. **Vultr VMs have no UART.** `/dev/console` was `ttyS0`, so `boot.sh`
   (`set -e`) died on its first message. That happened after the VPC IP was
   set but before the egress walls and the agent (run 5). Fix: `boot.sh`
   falls back to `tty0`.
   Evidence:
   - `S5/run5/G1-diagnosis.md`
   - `S5/run5/g1/serial-probe-on-bd-cp.txt`
   - the local reproduction, `local-e2e/kvm-noserial-prefix/` vs
     `local-e2e/kvm-noserial-fix-blank/`

## Console evidence

| run | screen after the restore | file |
|---|---|---|
| 4 | "Ubuntu 24.04.5 LTS - vultr login" (the clone booted) | `S5/checkpoints/console-2-take1.png` (`take2` is a noVNC "Failed to connect" frame) |
| 9 | clone's GRUB menu, `*bd-iso` selected, no countdown | `S5/run9/checkpoints/console-2-take1..3.png` |
| 10 | the same, after `timeout=3` + `recordfail` unset | `S5/run10/checkpoints/console-2-take1..2.png` |
| 11 | standalone GRUB at `grub>` (CD not visible to the firmware) | `S5/run11/checkpoints/console-2-take1.png` |
| 12 | `bd-oneshot: root=hd0,gpt1`, `EFI stub: Loaded initrd` | `S5/run12/checkpoints/console-2-take1.png` |
| 13 | the EFI-stub frame of the boot that registered sealed | `S5/run13/checkpoints/console-2-take1.png` |

noVNC refused synthetic key presses, so nothing on these screens was typed in
by hand (the `go-2` notes in `S5/run9/checkpoints/` and
`S5/run10/checkpoints/`).

## Operational findings

- **API reboot of an Ubuntu VM can lose SSH.** After `POST .../reboot`, SSH
  did not come back in 10 min. A guest `systemctl reboot` worked in 52 s
  (`S4/NOTES.md`, attempts 2 and 3). On the ISO twin the API reboot is a real
  reset (37 s outage, `S5/run5/g1/ping-from-bd-cp.log`). The ESP swap
  therefore reboots the clone from inside, with `systemctl reboot`
  (`S5/run13/esp-swap.txt`).
- **Metadata:** `/v1/user-data` returns 403/404 on live Vultr. The working
  endpoint is `GET /v1.json` with `Metadata-Token: cloudinit` (`S5/NOTES.md`).
- **The API key allowlist pins one machine IP.** On 2026-11-16, calls from
  another IP got 401 on ISO, object-storage, snapshot and VPC endpoints, while
  `/v2/instances` still returned 200. *No API response was saved at the time,
  so this claim has no evidence file.* `S3/result.json` is the ISO
  registration that succeeded once the IP was allowed.
- **Account ISO quota.** Registering a third ISO failed with "Please delete some
  existing ISOs before adding new ones". The obsolete run-3 ISO was deleted to
  make room (`S3/g3-iso-quota/001-delete-obsolete-run3-iso.json`).
- **A killed driver leaks resources and logs.** Run 6's driver was killed by
  the host (memory), so its `finally` never ran. The twin was locked by the
  restore (409) and was deleted 4 min later (`S5/run6/NOTES.md`,
  `S5/run6/killed-cleanup/`). Since then, long runs are launched detached
  (`Start-Process`), and `finally` saves bd-cp's log before deleting it
  (`S5/run13/cp-log.jsonl`, `S5/run13/057`-`060`).
- **herdr workers need `hc run --keep`.** Run 5's driver died with its
  herdr-core session while its instances kept running. `S5/run5/run.log`
  stops at the reboot line, and the two instances were still live 25 min later
  (`S5/run5/g1/001-g1-twin-before-reboot.json`).
