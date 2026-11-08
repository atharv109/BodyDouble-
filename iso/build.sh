#!/bin/sh
# iso/build.sh - build the Body Double forensics ISO inside an alpine container.
#
# The host only needs docker; ONE command from PowerShell (or any shell),
# volume paths in the Windows style test_plant.py already proves work here:
#
#   New-Item -ItemType Directory -Force iso\out | Out-Null
#   docker run --rm -v C:/dev/wt-forensics:/src:ro -v C:/dev/wt-forensics/iso/out:/out alpine:3.20 sh /src/iso/build.sh
#
# Produces /out/bodydouble-forensics.iso: a BIOS-bootable (isolinux +
# isohybrid) Alpine live system that boots INSTEAD of the cloned OS - the
# cloned disk is only ever mounted read-only afterwards. The image holds
# (PRD "Build plan" 2 / TASK.md iso item):
#   - python3 + the twin agent: forensics/bd_forensics/ and contracts/,
#     copied WHOLESALE to /usr/lib/bd, so later files ship for free
#   - docker + the gVisor runsc runtime (official static binary, downloaded
#     at build time - no key needed) for the F7 detonation sandbox
#   - nftables default-DROP egress that allows only the case VPC subnet
#   - the boot chain: initramfs init -> busybox init (inittab) ->
#     /etc/bd/boot.sh -> bd-twin (seal checks, register over the VPC with
#     the ONE-TIME token, long-poll /twin/jobs/next, post ToolResults)
#
# SECRET HYGIENE: nothing case-specific is baked. All deploy-time values
# arrive at boot from Vultr's link-local user_data
# as base64 JSON and are strictly validated in Python. No block-device or
# kernel-command-line configuration is accepted. No Vultr API key or inference key
# exists anywhere in the build context or the image.
#
# Modes:
#   (default)  full build: apk-install the target rootfs from the alpine
#              repositories, pack initramfs + squashfs, xorriso -> .iso
#   --stage    offline dry run for the test suite
#              (forensics/tests/test_iso_build.py): assembles and sha256-
#              manifests the exact image config the full build ships -
#              egress rules, live-ruleset demo, boot configs, bd-twin, the
#              copied agent packages - under /out/stage. No downloads, no
#              .iso; the files are byte-identical to what goes into the image.
#
# All work happens in the container's /tmp; only final artifacts are copied
# to /out (a host bind mount). If a full build fails mid-way, re-run it with
# `docker run ... sh -c 'sh /src/iso/build.sh || sh'` to get a shell in the
# kept container for inspection.
set -eu

SRC=${BD_SRC:-/src}     # repo root, mounted read-only
OUT=${BD_OUT:-/out}     # writable artifacts dir (host bind mount)
WORK=/tmp/bd-iso        # container-local scratch (fast, never on the host)
ISO_NAME=bodydouble-forensics.iso
VOLID=BDFORENSICS

OVERLAY="$SRC/iso/rootfs"
BOOTFILES="$SRC/iso/boot"

log() { echo "iso-build: $*"; }
die() { echo "iso-build: $*" >&2; exit 1; }

[ -f "$SRC/forensics/bd_forensics/twin.py" ] || die "repo not mounted at $SRC (BD_SRC)"
[ -d "$SRC/contracts" ] || die "$SRC/contracts not found"
[ -f "$BOOTFILES/init" ] || die "iso/boot files not found under $SRC/iso"
[ -d "$OUT" ] || die "output dir $OUT missing (BD_OUT; mount it writable)"

# copy the agent + contracts packages wholesale (no per-file lists, so later
# additions ship automatically); drop only interpreter caches
copy_agent_packages() {
    dst=$1
    mkdir -p "$dst"
    cp -a "$SRC/forensics/bd_forensics" "$dst/bd_forensics"
    cp -a "$SRC/contracts" "$dst/contracts"
    find "$dst" -type d -name __pycache__ -prune -exec rm -rf {} + 2>/dev/null || true
    find "$dst" -name '*.pyc' -delete 2>/dev/null || true
}

stage() {
    s="$WORK/stage"
    rm -rf "$WORK"
    mkdir -p "$s/tree/usr/lib/bd"

    log "stage: agent packages copied wholesale"
    copy_agent_packages "$s/tree/usr/lib/bd"

    log "stage: image config (rootfs overlay + boot files)"
    mkdir -p "$s/etc" "$s/usr" "$s/boot"
    cp -a "$OVERLAY/etc/." "$s/etc/"
    cp -a "$OVERLAY/usr/." "$s/usr/"
    cp -a "$BOOTFILES/." "$s/boot/"

    log "stage: live egress ruleset demo (fake deploy-time subnet)"
    # Demonstrate the validated Python renderer's final substitution using
    # the documentation-only RFC 5737 subnet.
    sed "s|__BD_VPC_SUBNET__|192.0.2.0/24|g" \
        "$s/etc/bd/egress.nft" > "$s/etc/bd/egress.live.nft"

    log "stage: sha256 manifest"
    ( cd "$s" && find . -type f ! -name manifest.txt -print0 | sort -z | xargs -0 sha256sum ) \
        > "$s/manifest.txt"

    rm -rf "$OUT/stage"
    cp -a "$s" "$OUT/stage"
    log "stage artifacts in $OUT/stage (image config only; no .iso)"
}

full() {
    log "installing ISO build tooling"
    apk add --no-cache xorriso syslinux squashfs-tools kmod busybox-static zstd

    ROOT="$WORK/rootfs"
    ISOROOT="$WORK/iso"
    INITRD="$WORK/initramfs"
    rm -rf "$WORK"
    mkdir -p "$ROOT" "$ISOROOT/boot/isolinux" "$INITRD"

    log "installing the target rootfs (alpine packages)"
    mkdir -p "$ROOT/etc/apk"
    cp -a /etc/apk/keys "$ROOT/etc/apk/keys"
    cp /etc/apk/repositories "$ROOT/etc/apk/repositories"
    apk add --root "$ROOT" --initdb --no-progress --clean-protected \
        alpine-base linux-lts python3 py3-httpx py3-pydantic docker nftables \
        ca-certificates

    log "gVisor runsc runtime (official release tarball + checksum)"
    GVISOR_URL=https://storage.googleapis.com/gvisor/releases/release/latest/x86_64
    wget -q -O "$WORK/gvisor.tar.zstd" "$GVISOR_URL/gvisor.tar.zstd"
    wget -q -O "$WORK/gvisor.tar.zstd.sha512" "$GVISOR_URL/gvisor.tar.zstd.sha512"
    ( cd "$WORK" && sha512sum -c gvisor.tar.zstd.sha512 )
    zstd -q -d -c "$WORK/gvisor.tar.zstd" | tar -xf - -C "$ROOT/usr/bin"
    chmod 755 "$ROOT/usr/bin/runsc"

    log "overlay: boot service, egress rules, inittab, agent packages"
    cp -a "$OVERLAY/." "$ROOT/"
    copy_agent_packages "$ROOT/usr/lib/bd"

    log "kernel and initramfs"
    KVER=$(ls "$ROOT/lib/modules" | head -n 1)
    cp "$ROOT/boot/vmlinuz-lts" "$ISOROOT/boot/vmlinuz-lts"

    mkdir -p "$INITRD/bin" "$INITRD/lib" "$INITRD/proc" "$INITRD/sys" \
        "$INITRD/dev" "$INITRD/run" "$INITRD/tmp" "$INITRD/media" "$INITRD/newroot"
    cp /bin/busybox.static "$INITRD/bin/busybox"
    chmod 755 "$INITRD/bin/busybox"

    # the modules the initramfs needs, dependency-first as resolved by kmod;
    # /modules lists the .ko paths, init insmods them in that order
    MODULES="loop squashfs isofs cdrom sr_mod virtio_blk virtio_scsi virtio_pci"
    : > "$INITRD/modules"
    for m in $MODULES; do
        modprobe -d "$ROOT" -S "$KVER" --show-depends "$m" 2>/dev/null \
            | grep '^insmod ' | cut -d' ' -f2 | sed "s|^$ROOT||" >> "$INITRD/modules" || true
    done
    awk '!seen[$0]++' "$INITRD/modules" > "$INITRD/modules.dedup"
    mv "$INITRD/modules.dedup" "$INITRD/modules"
    while IFS= read -r ko; do
        if [ -n "$ko" ]; then
            mkdir -p "$INITRD$(dirname "$ko")"
            cp "$ROOT$ko" "$INITRD$ko"
        fi
    done < "$INITRD/modules"

    cp "$BOOTFILES/init" "$INITRD/init"
    chmod 755 "$INITRD/init"
    ( cd "$INITRD" && find . | cpio -o -H newc | gzip -9 ) > "$ISOROOT/boot/initramfs-bd"

    log "packing the read-only root filesystem"
    mksquashfs "$ROOT" "$ISOROOT/rootfs.squashfs" -noappend -quiet

    log "boot loader"
    cp /usr/share/syslinux/isolinux.bin "$ISOROOT/boot/isolinux/"
    cp "$BOOTFILES/isolinux.cfg" "$ISOROOT/boot/isolinux/"

    log "xorriso -> $ISO_NAME"
    xorriso -as mkisofs -quiet -r -J -V "$VOLID" \
        -isohybrid-mbr /usr/share/syslinux/isohdpfx.bin \
        -b boot/isolinux/isolinux.bin -c boot/isolinux/boot.cat \
        -no-emul-boot -boot-load-size 4 -boot-info-table \
        -o "$WORK/$ISO_NAME" "$ISOROOT"

    log "manifest (rootfs contents + the .iso)"
    {
        ( cd "$ROOT" && find . -type f -print0 | sort -z | xargs -0 sha256sum ) \
            | sed "s|  \./|  rootfs/|"
        ( cd "$WORK" && sha256sum "$ISO_NAME" )
    } > "$WORK/manifest.txt"

    cp "$WORK/$ISO_NAME" "$OUT/$ISO_NAME"
    cp "$WORK/manifest.txt" "$OUT/manifest.txt"
    log "wrote $OUT/$ISO_NAME and $OUT/manifest.txt"
}

if [ "${1:-}" = "--stage" ]; then
    stage
else
    full
fi
