"""W1 (Gate 2) listener-side capture: an HTTP listener OUTSIDE Vultr that the
restored clone probes during the pre-swap window (boot -> ESP swap).

    python scripts/w1_listener.py --port 8765 --nonce <hex> --log <file.jsonl>

Run it on the operator machine before scripts/s5_twin.py --w1-listener-url ...;
the port must be reachable from the internet (router port-forward + Windows
firewall inbound rule). s5_twin self-tests that from bd-cp before the twin
exists. Every request is one JSON line: receive time (UTC, this machine's
clock), source IP:port, method, path. Only paths under /w1/<nonce>/ count as
probes; anything else (internet scanners) is logged with "probe": false.
The listener answers 200 with its receive time so the clone records both ends.
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--nonce", required=True, help="per-run secret path segment")
    ap.add_argument("--log", type=Path, required=True)
    args = ap.parse_args()
    args.log.parent.mkdir(parents=True, exist_ok=True)
    prefix = f"/w1/{args.nonce}/"

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            recv = datetime.now(timezone.utc).isoformat(timespec="microseconds")
            entry = {"recv_utc": recv, "src_ip": self.client_address[0],
                     "src_port": self.client_address[1], "method": self.command,
                     "path": self.path[:300], "probe": self.path.startswith(prefix)}
            with open(args.log, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry) + "\n")
            if entry["probe"]:
                print(f"{recv} probe from {entry['src_ip']} {self.path}", flush=True)
            body = f"bd-w1 ok {recv}\n".encode()
            self.send_response(200 if entry["probe"] else 404)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a) -> None:  # silence the default stderr log
            pass

    srv = ThreadingHTTPServer(("0.0.0.0", args.port), Handler)
    print(f"W1 listener on :{args.port}, probes under {prefix}, log {args.log}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
