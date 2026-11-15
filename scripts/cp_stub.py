"""Minimal control-plane stand-in for the real-mode day-one tests (T3/T4).

Runs on the bd-cp VM inside the case VPC, stdlib only:

    python3 cp_stub.py --bind 10.x.y.2 --port 8000 --case case-9001 \
        --token TOKEN --jobs jobs.json --log /root/cp.jsonl

Implements exactly the twin pull channel of contracts/endpoints.py
(POST /twin/register, GET /twin/jobs/next, POST /twin/jobs/{id}/result,
POST /twin/heartbeat) and logs every request with its SOURCE IP, which is the
T4 evidence. It is not the backend: no DB, no planner, a fixed job list.
The one-time token is consumed on first use, like the real control plane.
"""
from __future__ import annotations

import argparse
import json
import queue
import secrets
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

LOCK = threading.Lock()
STATE: dict = {"tokens": [], "sessions": {}, "jobs": queue.Queue(), "log": None}


def log(entry: dict) -> None:
    entry["at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    with LOCK, open(STATE["log"], "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")


class Handler(BaseHTTPRequestHandler):
    def _body(self) -> dict | None:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return None
        raw = self.rfile.read(n)
        try:
            return json.loads(raw)
        except ValueError:
            return {"_raw": raw.decode(errors="replace")}

    def _send(self, code: int, obj: dict | None = None) -> None:
        data = json.dumps(obj).encode() if obj is not None else b""
        self.send_response(code)
        if data:
            self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _session_ok(self) -> bool:
        key = self.headers.get("X-Twin-Session", "")
        return STATE["sessions"].get(key) == self.client_address[0]

    def do_POST(self) -> None:  # noqa: N802
        body = self._body()
        src = self.client_address[0]
        entry = {"src_ip": src, "method": "POST", "path": self.path}
        if self.path == "/twin/register":
            token = (body or {}).get("token")
            entry["body"] = {**(body or {}), "token": "<redacted>"}
            with LOCK:
                match = [t for t in STATE["tokens"] if token and secrets.compare_digest(token, t)]
                ok = bool(match)
                if ok:
                    STATE["tokens"].remove(match[0])  # each token works once
            if not ok:
                entry["status"] = 403
                log(entry)
                return self._send(403, {"detail": "unknown or already-used registration token"})
            key = "twinsess-" + secrets.token_urlsafe(24)
            STATE["sessions"][key] = src
            entry["status"] = 200
            log(entry)
            return self._send(200, {"session_key": key})
        if not self._session_ok():
            entry["status"] = 401
            log(entry)
            return self._send(401, {"detail": "bad session"})
        if self.path == "/twin/heartbeat":
            entry["status"] = 200
            log(entry)
            return self._send(200, {})
        if self.path.startswith("/twin/jobs/") and self.path.endswith("/result"):
            entry["body"] = body
            entry["status"] = 200
            log(entry)
            return self._send(200, {})
        entry["status"] = 404
        log(entry)
        self._send(404, {"detail": "not found"})

    def do_GET(self) -> None:  # noqa: N802
        src = self.client_address[0]
        entry = {"src_ip": src, "method": "GET", "path": self.path}
        if self.path != "/twin/jobs/next":
            entry["status"] = 404
            log(entry)
            return self._send(404, {"detail": "not found"})
        if not self._session_ok():
            entry["status"] = 401
            log(entry)
            return self._send(401, {"detail": "bad session"})
        try:
            job = STATE["jobs"].get(timeout=25)
        except queue.Empty:
            entry["status"] = 204
            log(entry)
            return self._send(204)
        entry["status"] = 200
        entry["job"] = job
        log(entry)
        self._send(200, job)

    def log_message(self, *_args) -> None:  # quiet stderr; the JSONL log is the record
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bind", required=True)
    ap.add_argument("--port", type=int, default=8000)
    ap.add_argument("--case", required=True)
    ap.add_argument("--token", required=True)
    ap.add_argument("--jobs", required=True)
    ap.add_argument("--log", required=True)
    a = ap.parse_args()
    STATE["tokens"], STATE["log"] = a.token.split(","), a.log  # comma list, each one-time
    for job in json.load(open(a.jobs, encoding="utf-8")):
        STATE["jobs"].put({**job, "case_id": a.case})
    log({"event": "listening", "bind": a.bind, "port": a.port, "jobs": STATE["jobs"].qsize()})
    ThreadingHTTPServer((a.bind, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
