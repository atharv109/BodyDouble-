#!/bin/sh
# Trusted ISO boot: network -> strictly validate link-local user_data in
# Python -> install default-DROP egress -> mount clone inert -> start twin.
# No configuration is ever read from the attacker-controlled cloned disk.
set -eu

BD_RUN=/run/bd
BD_MOUNT=/mnt/disk
mkdir -p "$BD_RUN" "$BD_MOUNT"
for d in /tmp /var/log /var/lib/docker; do
    mkdir -p "$d"
    mount -t tmpfs tmpfs "$d" 2>/dev/null || true
done

for i in /sys/class/net/*; do
    iface=${i##*/}
    if [ "$iface" != lo ]; then
        ip link set "$iface" up 2>/dev/null || true
        udhcpc -i "$iface" -n -q -t 4 -T 2 >/dev/null 2>&1 || true
    fi
done

bootstrap_ok=no
if bd-twin --configure-boot \
    --metadata-url http://169.254.169.254/v1/user-data \
    --nft-template /etc/bd/egress.nft \
    --nft-output "$BD_RUN/egress.live.nft" \
    --bootstrap-file "$BD_RUN/bootstrap.json"; then
    bootstrap_ok=yes
else
    echo "bd: invalid user_data; drop-only egress and no agent" >&2
fi
if ! nft -f "$BD_RUN/egress.live.nft"; then
    echo "bd: egress ruleset failed; no agent" >&2
    exit 1
fi

mounted=no
modprobe ext4 2>/dev/null || true
modprobe xfs 2>/dev/null || true
modprobe btrfs 2>/dev/null || true
for d in /dev/vdb /dev/vdc /dev/vdd /dev/sdb /dev/sdc /dev/sdd /dev/nvme0n2 /dev/nvme1n1; do
    if [ -b "$d" ] && mount -o ro,noexec,nosuid,nodev "$d" "$BD_MOUNT" 2>/dev/null; then
        if [ -d "$BD_MOUNT/etc" ]; then
            mounted=yes
            echo "bd: cloned disk mounted inert and read-only at $BD_MOUNT"
            break
        fi
        umount "$BD_MOUNT"
    fi
done
if [ "$mounted" = no ]; then
    echo "bd: cloned disk unavailable; twin will register unsealed" >&2
fi

if command -v dockerd >/dev/null 2>&1; then
    dockerd >/var/log/dockerd.log 2>&1 &
fi
if [ "$bootstrap_ok" = yes ]; then
    BD_MOUNT="$BD_MOUNT" bd-twin --bootstrap-file "$BD_RUN/bootstrap.json" \
        >/var/log/bd-twin.log 2>&1 &
else
    echo "bd: twin agent not started" >&2
fi
