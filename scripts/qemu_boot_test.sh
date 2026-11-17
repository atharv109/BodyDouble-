#!/bin/sh
# Local boot test of the forensics ISO before any Vultr spend (S2).
# Runs inside alpine:3.20 (needs no host qemu):
#
#   docker run --rm -v <repo>:/src:ro -v <repo>/iso/out:/out alpine:3.20 sh /src/scripts/qemu_boot_test.sh
#
# Builds a fake "cloned disk" (msdos label, ext4 vda1 holding /etc/hostname),
# boots /out/bodydouble-forensics.iso with it as the only virtio disk (the
# layout a twin created from a snapshot has), and records the serial console
# to /out/qemu-serial.log for BOOT_SECONDS. There is no Vultr metadata server
# here, so boot.sh must fall back to drop-only egress and NOT start the agent.
set -eu
BOOT_SECONDS=${BOOT_SECONDS:-240}
apk add --no-cache qemu-system-x86_64 qemu-img e2fsprogs sfdisk >/dev/null

W=/tmp/qt
mkdir -p "$W/root/etc"
echo shop-prod-clone > "$W/root/etc/hostname"
truncate -s 256M "$W/disk.img"
printf 'label: dos\nstart=2048, type=83\n' | sfdisk -q "$W/disk.img"
truncate -s 255M "$W/part.img"
mkfs.ext4 -q -d "$W/root" "$W/part.img"
dd if="$W/part.img" of="$W/disk.img" bs=1M seek=1 conv=notrunc status=none

accel=tcg
[ -e /dev/kvm ] && accel=kvm
timeout "$BOOT_SECONDS" qemu-system-x86_64 -machine accel=$accel -m 1024 -nographic \
    -cdrom /out/bodydouble-forensics.iso -boot d \
    -drive file="$W/disk.img",if=virtio,format=raw \
    -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
    -serial file:/out/qemu-serial.log -monitor none -display none || true
echo "qemu ($accel) done; serial log in /out/qemu-serial.log"
