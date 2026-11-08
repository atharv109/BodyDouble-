#!/bin/sh
# /etc/bd/boot.sh - one-shot boot service (busybox inittab ::sysinit:).
#
# Boot order is the security story of this ISO (PRD "Network walls", F4/F5):
#   1. read non-secret deploy parameters (VPC subnet, disk, VPC address).
#   2. bring the network up, then fetch base64(JSON {case_id, token,
#      control_plane}) from Vultr's link-local user_data metadata endpoint.
#      This happens before default-DROP; nothing untrusted runs this early.
#   3. load the nftables default-DROP egress ruleset: from here on only the
#      case VPC subnet is reachable. Fail closed: if the ruleset cannot be
#      loaded - or no subnet was provided - the twin agent NEVER starts.
#   4. mount the cloned disk READ-ONLY at /mnt/disk (bd_forensics.seal
#      MOUNT_POINT) so the seal check can verify it.
#   5. start dockerd (the F7 detonation sandbox backend) and the twin agent
#      (bd-twin): seal check, register with the control plane over the VPC
#      using the one-time token, then long-poll /twin/jobs/next and post
#      ToolResults.
set -eu

BD_RUN=/run/bd
BD_MOUNT=/mnt/disk

# ---- 0. writable corners on the read-only rootfs -----------------------
# the root filesystem is a read-only squashfs: logs, docker's storage and
# /tmp live on tmpfs. /run is already tmpfs (the initramfs moved it).
for d in /tmp /var/log /var/lib/docker; do
    mkdir -p "$d"
    mount -t tmpfs tmpfs "$d" 2>/dev/null || true
done

mkdir -p "$BD_RUN" "$BD_MOUNT"

# ---- 1. deploy-time parameters ----------------------------------------
BD_CASE_ID=
BD_TOKEN=
BD_SUBNET=
BD_CP=
BD_VPC_IP=
BD_DISK=

# the attached file and cmdline carry only non-secret network/device values
if [ -f "$BD_RUN/deploy.env" ]; then
    . "$BD_RUN/deploy.env"
fi

for arg in $(cat /proc/cmdline); do
    case "$arg" in
        bd.subnet=*)  BD_SUBNET=${arg#bd.subnet=} ;;
        bd.vpc_ip=*)  BD_VPC_IP=${arg#bd.vpc_ip=} ;;
        bd.disk=*)    BD_DISK=${arg#bd.disk=} ;;
    esac
done

# ---- 2. network up before the walls go up ------------------------------
for i in /sys/class/net/*; do
    iface=${i##*/}
    if [ "$iface" != lo ]; then
        ip link set "$iface" up 2>/dev/null || true
        udhcpc -i "$iface" -n -q -t 4 -T 2 >/dev/null 2>&1 || true
    fi
done

# Vultr user_data is base64(JSON {case_id, token, control_plane}). Fetch it
# exactly once from link-local metadata before the wall is installed. The
# resulting file lives only on /run tmpfs and is root-readable.
METADATA_URL=${BD_METADATA_URL:-http://169.254.169.254/v1/user-data}
umask 077
if bd-twin --fetch-metadata "$METADATA_URL" --env-file "$BD_RUN/metadata.env"; then
    . "$BD_RUN/metadata.env"
else
    echo "bd: metadata bootstrap failed - twin agent will not start" >&2
fi

# ---- 3. egress: default DROP, only the case VPC subnet ----------------
if [ -n "$BD_SUBNET" ]; then
    sed "s|__BD_VPC_SUBNET__|$BD_SUBNET|g" \
        /etc/bd/egress.nft > "$BD_RUN/egress.live.nft"
else
    # fail closed: no deploy-time subnet means allow nothing anywhere
    grep -v "__BD_VPC_SUBNET__" /etc/bd/egress.nft > "$BD_RUN/egress.live.nft"
    echo "bd: no case VPC subnet (bd.subnet=) - staying dark" >&2
fi

if ! nft -f "$BD_RUN/egress.live.nft"; then
    echo "bd: egress ruleset FAILED to load - NOT starting the twin agent" >&2
    exit 1
fi
echo "bd: egress default-DROP loaded (allow: VPC subnet only)"

# ---- 4. the cloned disk, read-only ------------------------------------
mounted=no
if [ -n "$BD_DISK" ]; then
    if mount -o ro "$BD_DISK" "$BD_MOUNT" 2>/dev/null; then
        mounted=yes
    else
        echo "bd: $BD_DISK failed to mount read-only" >&2
    fi
else
    # the deploy step did not pin the device: try every disk that carries a
    # Linux root (has /etc). The ISO itself boots from /dev/sr0 and never
    # matches. bd-deploy.env config devices hold no /etc and are skipped.
    modprobe ext4 2>/dev/null || true
    modprobe xfs 2>/dev/null || true
    modprobe btrfs 2>/dev/null || true
    for d in /dev/vdb /dev/vdc /dev/vdd /dev/sdb /dev/sdc /dev/sdd /dev/nvme0n2 /dev/nvme1n1; do
        if [ -b "$d" ]; then
            if mount -o ro "$d" "$BD_MOUNT" 2>/dev/null; then
                if [ -d "$BD_MOUNT/etc" ]; then
                    mounted=yes
                    echo "bd: cloned disk $d mounted read-only at $BD_MOUNT"
                    break
                fi
                umount "$BD_MOUNT"
            fi
        fi
    done
fi
if [ "$mounted" = no ]; then
    echo "bd: no cloned disk mounted read-only; twin registers unsealed" >&2
fi

# ---- 5. sandbox backend + twin agent ---------------------------------
if command -v dockerd >/dev/null 2>&1; then
    dockerd >/var/log/dockerd.log 2>&1 &
    echo "bd: dockerd started (detonation sandbox backend)"
fi

if [ -n "$BD_CASE_ID" ] && [ -n "$BD_TOKEN" ] && [ -n "$BD_CP" ]; then
    set -a
    . "$BD_RUN/metadata.env"
    set +a
    export BD_VPC_IP BD_MOUNT
    bd-twin >/var/log/bd-twin.log 2>&1 &
    echo "bd: twin agent started for case $BD_CASE_ID"
else
    echo "bd: missing bd.case/bd.token/bd.cp deploy parameters - twin agent NOT started" >&2
fi
