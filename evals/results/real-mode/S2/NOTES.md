# S2 evidence: local QEMU boot of bodydouble-forensics.iso

- Build method (Windows): the ISO was built in an `alpine:3.20` Docker container
  via `iso/build.sh`; output `iso/out/bodydouble-forensics.iso` (393,216,000 bytes).
- Boot test: `scripts/qemu_boot_test.sh`, run in a plain `alpine:3.20` container
  so the host needs no QEMU. It synthesizes a fake "cloned twin" disk
  (msdos label, one ext4 vda1 holding only `/etc/hostname`) and boots the ISO
  as the sole CD-ROM with that disk as the only virtio drive — the layout an
  instance created from a snapshot has. No Vultr metadata server is present,
  so the boot must take the invalid-user_data fallback.
- `qemu-serial.log` (this folder) is the full serial console of the passing run.
  Gates visible in it:
  - `bd-init: boot media /dev/sr0` — boot media found after the new retry loop.
  - `bd: invalid user_data; drop-only egress and no agent` — expected fallback.
  - `bd: cloned disk /dev/vda1 mounted inert and read-only at /mnt/disk` —
    clone mounted with `blockdev --setro` + `ro,noload` (zero writes).
  - `bd: sandbox image loaded; runtimes: {"io.containerd.runc.v2":...` —
    dockerd up, sandbox image loaded from the ISO.
  - `bd: twin agent not started` and a login prompt — clean idle state.
- `iso-manifest.txt` is the sha256 manifest of the built rootfs, proving the
  ISO contains `rootfs/usr/bin/bd-vpc-up`, `rootfs/usr/bin/runsc`, and
  `rootfs/usr/share/bd/sandbox-image.tar`.
- `qemu_boot_test.sh` is the exact script used (also in scripts/).

Upload: the ISO is uploaded as a GitHub release asset on
https://github.com/atharv109/BodyDouble- (repo is public); see the
"Release asset" note appended below once curl -I returns 200.
