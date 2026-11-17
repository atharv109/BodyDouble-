"""Probe what Vultr's metadata /v1.json actually serves for user_data, over time.

    uv run python scripts/md_probe.py

Creates one tagged throwaway instance (deleted in finally), puts a plain
marker string as user_data (base64 in the create call, like bd-cp/real twins),
and polls GET /v1.json (Metadata-Token: cloudinit) from inside the instance,
recording every fetch. Answers: does the service serve the DECODED string, the
BASE64 string it stored, when (boot-time dependence), and does one form flip
to the other while the instance lives.
"""
from __future__ import annotations

import base64
import json
import sys
import time

sys.path.insert(0, __import__("os").path.dirname(__file__))
from bdvultr import Api, evidence, load_secrets  # noqa: E402
from s4_shop_prod import PLAN, REGION, UBUNTU_2404, ssh, wait_ssh  # noqa: E402

MARKER = "bd-probe-marker-20261115"
OUT = evidence("S5")


def main() -> int:
    api = Api(load_secrets()["VULTR_API_KEY"], evidence_dir=OUT)
    created: list[str] = []
    try:
        inst = api.call("POST", "/v2/instances", {
            "region": REGION, "plan": PLAN, "os_id": UBUNTU_2404, "label": "bd-md-probe",
            "hostname": "bd-md-probe", "tags": ["body-double"], "backups": "disabled",
            "sshkey_id": [load_secrets()["SSHKEY_ID"]],
            "user_data": base64.b64encode(MARKER.encode()).decode(),
        }, name="create-probe")[1]["instance"]
        created.append(inst["id"])
        inst, took = api.wait(f"/v2/instances/{inst['id']}", "instance", "status", "active", 900, 10)
        ip = inst["main_ip"]
        print(f"probe {inst['id']} active in {took:.0f}s, ip {ip}", flush=True)
        wait_ssh(ip)
        for _ in range(7):  # ~15 min of samples
            r = ssh(ip, "curl -s -m 8 -H 'Metadata-Token: cloudinit' http://169.254.169.254/v1.json",
                    check=False)
            entry = {"t": time.strftime("%H:%M:%S"), "raw_head": r[:80]}
            try:
                ud = json.loads(r).get("user-data", "")
                entry["user_data_head"] = ud[:40]
                entry["is_decoded"] = ud == MARKER
                entry["is_stored_b64"] = ud == base64.b64encode(MARKER.encode()).decode()
            except ValueError:
                entry["parse_error"] = True
            line = json.dumps(entry)
            print(line, flush=True)
            with open(OUT / "md-probe.jsonl", "a", encoding="utf-8") as f:
                f.write(line + "\n")
            time.sleep(120)
        return 0
    finally:
        for iid in created:
            api.call("DELETE", f"/v2/instances/{iid}", name="cleanup-probe", ok=(404,))


if __name__ == "__main__":
    sys.exit(main())
