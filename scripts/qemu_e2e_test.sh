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
set -eu
BOOT_SECONDS=${BOOT_SECONDS:-900}
apk add --no-cache qemu-system-x86_64 e2fsprogs sfdisk python3 iproute2 >/dev/null

W=/tmp/qt
rm -rf "$W" && mkdir -p "$W/root"
cp -a /src/demo/victim/. "$W/root/"
truncate -s 256M "$W/disk.img"
printf 'label: dos\nstart=2048, type=83\n' | sfdisk -q "$W/disk.img"
truncate -s 255M "$W/part.img"
mkfs.ext4 -q -d "$W/root" "$W/part.img"
dd if="$W/part.img" of="$W/disk.img" bs=1M seek=1 conv=notrunc status=none

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
        with open("/out/md.jsonl", "a") as f:
            f.write(json.dumps({"at": time.strftime("%H:%M:%S"), "src": self.client_address[0],
                                "path": self.path, "served": ok}) + "\n")
        self.send_response(200 if ok else 404)
        self.send_header("Content-Length", str(len(BODY) if ok else 0))
        self.end_headers()
        if ok:
            self.wfile.write(BODY)
HTTPServer(("169.254.169.254", 80), H).serve_forever()
EOF
rm -f /out/md.jsonl /out/cp.jsonl /out/serial.log
python3 "$W/md.py" "$W/v1.json" &

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
python3 /src/scripts/cp_stub.py --bind 10.1.96.3 --port 8000 --case case-9001 \
    --token "$TOKEN" --jobs "$W/jobs.json" --log /out/cp.jsonl &

accel=tcg
[ -e /dev/kvm ] && accel=kvm
timeout "$BOOT_SECONDS" qemu-system-x86_64 -machine accel=$accel -m 1024 -nographic \
    -cdrom /iso/bodydouble-forensics.iso -boot d \
    -drive file="$W/disk.img",if=virtio,format=raw \
    -netdev user,id=n0 -device virtio-net-pci,netdev=n0 \
    -netdev tap,id=n1,ifname=tap0,script=no,downscript=no -device virtio-net-pci,netdev=n1 \
    -serial file:/out/serial.log -monitor none -display none || true
echo "qemu ($accel) done; serial /out/serial.log, md /out/md.jsonl, cp /out/cp.jsonl"
