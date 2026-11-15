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

Upload: gh cannot create a release (the operator's fine-grained PAT lacks
"Contents: write" and only this token is available), so with the operator's
go-ahead the ISO is published on a short-lived Vultr Object Storage
subscription instead — the fallback TASK.md sanctions. Details:

- Subscription 9dad724e-514f-4762-8525-d4fba9e1ef51, label bd-iso-upload,
  cluster ewr1, tier Archival (the API's cheapest tier that serves ewr), in
  bucket bd-iso-upload at key forensics/bodydouble-forensics.iso. Uploaded in
  96 s (393,216,000 B, multipart). scripts/bd_iso.py created all of it.
- The signed HTTPS URLs (7-day presigned GET and HEAD) live only in
  .bd-secrets.env as BD_ISO_URL / BD_ISO_URL_HEAD — the signatures are derived
  from the S3 credentials and stay out of the repo.
- curl-I.txt is the literal `curl -I` (HEAD) response: HTTP/1.1 200 OK,
  content-length: 393216000 — the S2 done-when. (schannel needed a retry; the
  URL always returned 200 once the TLS handshake completed.)
- scripts/vultr_sweep.py deletes bd-* object-storage subscriptions (S6), so
  the publisher costs ~$0.008/hr only while the real-mode runs need it.
- iso-sha256.txt holds the SHA256 of the exact ISO uploaded/boot-tested.
