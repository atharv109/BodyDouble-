#!/bin/sh
# Local end-to-end test of the forensics ISO's SUCCESS path (F1/F2 diagnosis).
# Unlike qemu_boot_test.sh, this gives the ISO everything Vultr gives a twin:
#
#   docker run --rm --cap-add NET_ADMIN --device /dev/net/tun \
#     -v <repo>:/src:ro -v <repo>/evals/results/local-e2e:/out \
#     -v <repo>/iso/out:/iso:ro alpine:3.20 sh /src/scripts/qemu_e2e_test.sh
#
# - eth0 "public": QEMU user net with DHCP + default route. The Vultr metadata
#   service is emulated at 169.254.169.254:80 (an address on the container's
#   lo; slirp NATs the guest's connection to it), serving /v1.json whose
#   user-data field is base64(bootstrap JSON) - the as-stored form measured in
#   S5 runs 2 and 3.
# - eth1 "VPC": a tap on a bridge holding the control plane 10.1.96.3/20, with
#   NO DHCP, like a Vultr VPC. scripts/cp_stub.py listens there only.
# - the only disk is a msdos-labelled ext4 vda1 holding demo/victim (the
#   planted indicators), the layout of a twin restored from the S4 snapshot.
# Pass: /out/cp.jsonl shows register + 3 job results from 10.1.96.20.
#
# Also runs as root in a WSL2/Linux host with /dev/kvm (KVM + -cpu host, like a
# Vultr twin), isolated in its own network namespace:
#   SRC=<repo> OUT=<dir> ISO=<repo>/iso/out unshare --net sh scripts/qemu_e2e_test.sh
# BLANK_DISK=1 gives the twin an empty disk: the state before the restore (T1b).
# NO_SERIAL=1 boots without a UART, as every Vultr VM does (S5 run 5, G1).
set -eu
BOOT_SECONDS=${BOOT_SECONDS:-900}
SRC=${SRC:-/src}
OUT=${OUT:-/out}
ISO=${ISO:-/iso}
if command -v apk >/dev/null 2>&1; then
    apk add --no-cache qemu-system-x86_64 e2fsprogs sfdisk python3 iproute2 >/dev/null
fi
ip link set lo up

W=/tmp/qt
rm -rf "$W" && mkdir -p "$W/root"
truncate -s 256M "$W/disk.img"
if [ "${UEFI_GRUB:-0}" = 1 ]; then
    # UEFI_GRUB=1: the clone as Vultr restores it (S5 run 9/10: UEFI, GPT, ESP vda1
    # + ext4 root vda2), booted by OVMF. The ESP's fallback loader
    # \EFI\BOOT\BOOTX64.EFI is a standalone GRUB that boots the ISO's kernel at
    # once: no menu, no timeout. This is the ESP-swap one-shot.
    cp -a "$SRC/demo/victim/." "$W/root/"
    truncate -s 400M "$W/disk.img"
    printf 'label: gpt\nstart=2048, size=262144, type=U\nstart=264192, size=522240, type=L\n' \
        | sfdisk -q "$W/disk.img"
    # the exact binary s5_twin.py installs live (scripts/build_oneshot_efi.sh)
    cp "$ISO/bd-oneshot-x64.efi" "$W/BOOTX64.EFI"
    mkfs.vfat -C "$W/esp.img" 131072 >/dev/null
    mmd -i "$W/esp.img" ::/EFI ::/EFI/BOOT
    mcopy -i "$W/esp.img" "$W/BOOTX64.EFI" ::/EFI/BOOT/BOOTX64.EFI
    truncate -s 255M "$W/part.img"
    mkfs.ext4 -q -d "$W/root" "$W/part.img"
    dd if="$W/esp.img" of="$W/disk.img" bs=1M seek=1 conv=notrunc status=none
    dd if="$W/part.img" of="$W/disk.img" bs=1M seek=129 conv=notrunc status=none
elif [ "${BLANK_DISK:-0}" != 1 ]; then
    cp -a "$SRC/demo/victim/." "$W/root/"
    printf 'label: dos\nstart=2048, type=83\n' | sfdisk -q "$W/disk.img"
    truncate -s 255M "$W/part.img"
    mkfs.ext4 -q -d "$W/root" "$W/part.img"
    dd if="$W/part.img" of="$W/disk.img" bs=1M seek=1 conv=notrunc status=none
fi

# metadata service
ip addr add 169.254.169.254/32 dev lo
TOKEN=e2e$(head -c 8 /dev/urandom | od -An -tx1 | tr -d ' \n')
python3 - "$TOKEN" > "$W/v1.json" <<'EOF'
import base64, json, sys
p = {"case_id": "case-9001", "token": sys.argv[1], "control_plane": "http://10.1.96.3:8000",
     "vpc_subnet": "10.1.96.0/20", "vpc_ip": "10.1.96.20"}
print(json.dumps({"user-data": base64.b64encode(json.dumps(p).encode()).decode()}))
EOF
cat > "$W/md.py" <<'EOF'
import json, sys, time
from http.server import BaseHTTPRequestHandler, HTTPServer
BODY = open(sys.argv[1], "rb").read()
class H(BaseHTTPRequestHandler):
    def do_GET(self):
        ok = self.path == "/v1.json" and self.headers.get("Metadata-Token") == "cloudinit"
        with open(sys.argv[2], "a") as f:
            f.write(json.dumps({"at": time.strftime("%H:%M:%S"), "src": self.client_address[0],
                                "path": self.path, "served": ok}) + "\n")
        self.send_response(200 if ok else 404)
        self.send_header("Content-Length", str(len(BODY) if ok else 0))
        self.end_headers()
        if ok:
            self.wfile.write(BODY)
HTTPServer(("169.254.169.254", 80), H).serve_forever()
EOF
mkdir -p "$OUT"
rm -f "$OUT/md.jsonl" "$OUT/cp.jsonl" "$OUT/serial.log"
python3 "$W/md.py" "$W/v1.json" "$OUT/md.jsonl" &

# VPC: bridge + tap, no DHCP
ip link add br0 type bridge
ip addr add 10.1.96.3/20 dev br0
ip tuntap add tap0 mode tap
ip link set tap0 master br0
ip link set br0 up
ip link set tap0 up
cat > "$W/jobs.json" <<'EOF'
[{"job_id": "job-os-facts", "tool": "os_facts", "args": {}},
 {"job_id": "job-persistence", "tool": "persistence_scan", "args": {}},
 {"job_id": "job-detonate-bdrv", "tool": "detonate", "args": {"path": "usr/local/bin/.bdrv"}}]
EOF
python3 "$SRC/scripts/cp_stub.py" --bind 10.1.96.3 --port 8000 --case case-9001 \
    --token "$TOKEN" --jobs "$W/jobs.json" --log "$OUT/cp.jsonl" &

# NO_SERIAL=1: no UART at all, like a Vultr VM (/proc/tty/driver/serial: uart:unknown)
serial=file:"$OUT/serial.log"
[ "${NO_SERIAL:-0}" = 1 ] && serial=none
accel=tcg cpu=qemu64
[ -e /dev/kvm ] && accel=kvm cpu=host
fw="-boot d"
if [ "${UEFI_GRUB:-0}" = 1 ]; then
    cp /usr/share/OVMF/OVMF_VARS_4M.fd "$W/vars.fd"
    fw="-machine q35 -drive if=pflash,format=raw,readonly=on,file=/usr/share/OVMF/OVMF_CODE_4M.fd
        -drive if=pflash,format=raw,file=$W/vars.fd"
fi
# shellcheck disable=SC2086
timeout "$BOOT_SECONDS" qemu-system-x86_64 -machine accel=$accel -cpu $cpu -m 1024 -nographic \
    -cdrom "$ISO/bodydouble-forensics.iso" $fw \
    -drive file="$W/disk.img",if=virtio,format=raw \
    -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
    -netdev tap,id=n1,ifname=tap0,script=no,downscript=no -device virtio-net-pci,netdev=n1 \
    -serial "$serial" -monitor none -display none || true
echo "qemu ($accel) done; serial $OUT/serial.log, md $OUT/md.jsonl, cp $OUT/cp.jsonl"
