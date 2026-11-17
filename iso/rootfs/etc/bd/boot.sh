#!/bin/sh
# Trusted ISO boot: network -> strictly validate link-local user_data in
# Python -> install default-DROP egress -> mount clone inert -> start twin.
# No configuration is ever read from the attacker-controlled cloned disk.
set -eu

# Real-mode finding (S5 run 5, evals/results/real-mode/S5/run5/G1-diagnosis.md):
# Vultr VMs have no UART, so /dev/console (ttyS0, the last console= in
# isolinux.cfg) returns EIO. Under set -e the first message - bd-vpc-up's -
# killed this script before the egress walls and the agent. Probe the console
# once; if it is dead, write everything to tty0 (the VNC screen) instead.
if ! echo "bd: boot.sh starting" 2>/dev/null; then
    exec >/dev/tty0 2>&1
    echo "bd: no serial console; boot messages on tty0"
fi

BD_RUN=/run/bd
BD_MOUNT=/mnt/disk
mkdir -p "$BD_RUN" "$BD_MOUNT"
for d in /tmp /var/log /var/lib/docker; do
    mkdir -p "$d"
    mount -t tmpfs tmpfs "$d" 2>/dev/null || true
done

# no udev/mdev in this appliance: load the NIC drivers ourselves (virtio on
# Vultr/KVM; e1000 as a fallback), then give the links a moment to appear
modprobe -a virtio_net e1000 2>/dev/null || true
sleep 2
# dockerd needs the unified cgroup hierarchy (normally mounted by openrc)
mount -t cgroup2 cgroup2 /sys/fs/cgroup 2>/dev/null || true

for i in /sys/class/net/*; do
    iface=${i##*/}
    if [ "$iface" != lo ]; then
        ip link set "$iface" up 2>/dev/null || true
        udhcpc -i "$iface" -n -q -t 4 -T 2 >/dev/null 2>&1 || true
    fi
done

bootstrap_ok=no
if bd-twin --configure-boot \
    --metadata-url http://169.254.169.254/v1.json \
    --nft-template /etc/bd/egress.nft \
    --nft-output "$BD_RUN/egress.live.nft" \
    --bootstrap-file "$BD_RUN/bootstrap.json"; then
    bootstrap_ok=yes
    # Vultr VPCs have no DHCP: assign the validated vpc_ip statically (T4)
    bd-vpc-up "$BD_RUN/bootstrap.json" || echo "bd: VPC interface not configured" >&2
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
# Real-mode finding (T1): the twin is created FROM the snapshot, so the clone
# is the only disk (/dev/vda) and its root is a partition (vda1). Scan
# partitions and whole disks; the CD-ROM boot media (sr*) is never a candidate.
# blockdev --setro first: the kernel then refuses every write, even an ext4
# journal replay, so "ro" really means zero writes to the clone.
for d in /dev/vd[a-z]* /dev/sd[a-z]* /dev/nvme[0-9]n[0-9]*; do
    [ -b "$d" ] || continue
    blockdev --setro "$d" 2>/dev/null || true
    if mount -t ext4 -o ro,noexec,nosuid,nodev,noload "$d" "$BD_MOUNT" 2>/dev/null \
        || mount -o ro,noexec,nosuid,nodev "$d" "$BD_MOUNT" 2>/dev/null; then
        if [ -d "$BD_MOUNT/etc" ]; then
            mounted=yes
            echo "bd: cloned disk $d mounted inert and read-only at $BD_MOUNT"
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
    # the sandbox image ships in the ISO; the twin can never pull one
    for _ in $(seq 1 30); do docker info >/dev/null 2>&1 && break; sleep 1; done
    if [ -f /usr/share/bd/sandbox-image.tar ]; then
        if docker load -i /usr/share/bd/sandbox-image.tar >/var/log/docker-load.log 2>&1; then
            echo "bd: sandbox image loaded; runtimes: $(docker info --format '{{json .Runtimes}}' 2>&1 | head -c 120)"
        else
            echo "bd: sandbox image load failed:" >&2
            tail -n 5 /var/log/docker-load.log /var/log/dockerd.log >&2
        fi
    fi
fi
if [ "$bootstrap_ok" = yes ]; then
    BD_MOUNT="$BD_MOUNT" bd-twin --bootstrap-file "$BD_RUN/bootstrap.json" \
        >/var/log/bd-twin.log 2>&1 &
else
    echo "bd: twin agent not started" >&2
fi
