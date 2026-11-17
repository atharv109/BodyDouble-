"""Shared helpers for the real-mode infrastructure scripts.

- load_secrets(): reads %USERPROFILE%\\.bd-secrets.env (never printed, never in git)
- Api: a tiny sync Vultr v2 client that can record every response, redacted,
  under evals/results/real-mode/<item>/ so findings stay reproducible.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

import httpx

REPO = Path(__file__).resolve().parent.parent
EVIDENCE_ROOT = REPO / "evals" / "results" / "real-mode"
SECRETS_FILE = Path(os.environ.get("USERPROFILE", str(Path.home()))) / ".bd-secrets.env"

# keys whose values never reach disk or stdout
REDACT_KEYS = {"default_password", "password", "api_key", "token", "secret_key",
               "access_key", "user_data", "kvm"}


def load_secrets(path: Path = SECRETS_FILE) -> dict[str, str]:
    env: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip()
    return env


def set_secret(key: str, value: str, path: Path = SECRETS_FILE) -> None:
    """Replace (or append) KEY=value in the secrets file without echoing anything."""
    lines = path.read_text(encoding="utf-8").splitlines()
    out, done = [], False
    for line in lines:
        if re.match(rf"^\s*{re.escape(key)}\s*=", line):
            out.append(f"{key}={value}")
            done = True
        else:
            out.append(line)
    if not done:
        out.append(f"{key}={value}")
    path.write_text("\n".join(out) + "\n", encoding="utf-8")


def redact(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: ("<redacted>" if k in REDACT_KEYS else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


class Api:
    BASE = "https://api.vultr.com"

    def __init__(self, api_key: str, evidence_dir: Path | None = None,
                 transport: httpx.BaseTransport | None = None):
        self._http = httpx.Client(base_url=self.BASE, timeout=60, transport=transport,
                                  headers={"Authorization": f"Bearer {api_key}"})
        self.evidence_dir = evidence_dir
        self._n = 0

    def call(self, method: str, path: str, body: dict | None = None,
             name: str | None = None, ok: tuple[int, ...] = ()) -> tuple[int, Any]:
        r = self._http.request(method, path, json=body)
        data = r.json() if r.content and "json" in r.headers.get("content-type", "") else (r.text or None)
        if self.evidence_dir is not None:
            self._n += 1
            self.evidence_dir.mkdir(parents=True, exist_ok=True)
            label = name or re.sub(r"[^A-Za-z0-9]+", "-", f"{method}-{path}").strip("-")[:80]
            rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "method": method,
                   "path": path, "request": redact(body), "status": r.status_code,
                   "response": redact(data)}
            (self.evidence_dir / f"{self._n:03d}-{label}.json").write_text(
                json.dumps(rec, indent=2), encoding="utf-8")
        if r.status_code >= 400 and r.status_code not in ok:
            raise RuntimeError(f"Vultr {method} {path} -> {r.status_code}: {redact(data)}")
        return r.status_code, data

    def get(self, path: str, **kw) -> Any:
        return self.call("GET", path, **kw)[1]

    def list_all(self, path: str, key: str) -> list[dict]:
        out, cursor = [], ""
        while True:
            sep = "&" if "?" in path else "?"
            # /v2/snapshots rejects an empty cursor= (400 invalid cursor)
            data = self.get(f"{path}{sep}per_page=100" + (f"&cursor={cursor}" if cursor else ""))
            out += data.get(key, [])
            cursor = (data.get("meta") or {}).get("links", {}).get("next", "")
            if not cursor:
                return out

    def wait(self, path: str, key: str, field: str, want: str,
             timeout_s: float, every_s: float = 15) -> tuple[dict, float]:
        """Poll GET path until obj[field] == want. Returns (obj, seconds waited)."""
        t0 = time.monotonic()
        while True:
            obj = self.get(path)[key]
            if obj.get(field) == want:
                return obj, time.monotonic() - t0
            if time.monotonic() - t0 > timeout_s:
                raise TimeoutError(f"{path}: {field}={obj.get(field)!r} after {timeout_s}s")
            time.sleep(every_s)


def evidence(item: str) -> Path:
    d = EVIDENCE_ROOT / item
    d.mkdir(parents=True, exist_ok=True)
    return d
