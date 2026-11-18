"""S1: sweep every Body Double resource off the Vultr account and print the burn.

    uv run python scripts/vultr_sweep.py            # delete project resources
    uv run python scripts/vultr_sweep.py --dry-run  # list only

Deletes ONLY resources marked as ours:
  instances        tag "body-double" or label "bd-*"
  snapshots        description contains "body-double" or starts "bd-",
                   EXCEPT the case-NNNN snapshots (case-0001/case-0002), never touched
  VPCs, firewalls  description contains "body-double" or starts "bd-"
  object storage   label starts "bd-" (the short-lived bd-iso-upload ISO publisher)
  ISOs             filename contains "body-double" or starts "bd-"
  reserved IPs     label contains "body-double"/"bodydouble" or starts "bd-" (bd-cp's
                   allowlisted IP, Gate 2 B3); the one in BD_CP_RESERVED_IP_ID is kept
                   unless --release-reserved-ip (the gate's FINAL sweep)
  NAT gateways     label contains "body-double" or starts "bd-", on ANY VPC (kept
                   VPCs included: a NAT gateway bills hourly). No flat list exists
                   (POST/GET /v2/nat-gateways -> 404, W2b evidence); they live under
                   /v2/vpcs/{vpc}/nat-gateway. List/delete shapes follow the Vultr
                   docs and are confirmed live in
                   evals/results/real-run-01/preswap-isolation/findings.md.
Resources the secrets file points at (VULTR_ISO_ID, BD_VPC_ID) and the shop-prod
snapshot the twin is restored from (evals/results/real-mode/S4/result.json) are kept unless
--include-env-refs is given: they cost $0/hr and the app needs them.
delete() re-checks owned() itself, so nothing else can be deleted by mistake.
"""
from __future__ import annotations

import argparse
import re
import sys
import time

sys.path.insert(0, __import__("os").path.dirname(__file__))
from bdvultr import REPO, Api, load_secrets  # noqa: E402

TAG = "body-double"
PROTECTED_SNAPSHOT = re.compile(r"\bcase-\d{4}\b")
SNAPSHOT_USD_PER_GB_MONTH = 0.05
HOURS_PER_MONTH = 730

# kind -> (list path, list key, delete path prefix)
KINDS = {
    "instance": ("/v2/instances", "instances", "/v2/instances"),
    "snapshot": ("/v2/snapshots", "snapshots", "/v2/snapshots"),
    "firewall": ("/v2/firewalls", "firewall_groups", "/v2/firewalls"),
    "vpc": ("/v2/vpcs", "vpcs", "/v2/vpcs"),
    "object_storage": ("/v2/object-storage", "object_storages", "/v2/object-storage"),
    "iso": ("/v2/iso", "isos", "/v2/iso"),
    "reserved_ip": ("/v2/reserved-ips", "reserved_ips", "/v2/reserved-ips"),
}
ORDER = ["instance", "snapshot", "firewall", "nat_gateway", "vpc", "object_storage", "iso",
         "reserved_ip"]
# instances first; NAT gateways before their VPC


def list_nat_gateways(api: Api) -> list[dict]:
    """Every NAT gateway on the account: one GET per VPC (404 = none there).
    Each item gets vpc_id filled in from the VPC it was listed under."""
    out = []
    for vpc in api.list_all("/v2/vpcs", "vpcs"):
        status, data = api.call("GET", f"/v2/vpcs/{vpc['id']}/nat-gateway", ok=(404,))
        if status == 404 or not isinstance(data, dict):
            continue
        items = data.get("nat_gateways")
        if items is None:  # tolerate a single-object answer
            items = [data["nat_gateway"]] if data.get("nat_gateway") else []
        out += [{**i, "vpc_id": i.get("vpc_id") or vpc["id"]} for i in items]
    return out


def list_kind(api: Api, kind: str) -> list[dict]:
    if kind == "nat_gateway":
        return list_nat_gateways(api)
    path, key, _ = KINDS[kind]
    return api.list_all(path, key)


def delete_path(kind: str, item: dict) -> str:
    if kind == "nat_gateway":
        return f"/v2/vpcs/{item['vpc_id']}/nat-gateway/{item['id']}"
    return f"{KINDS[kind][2]}/{item['id']}"


class RefusedDelete(Exception):
    """delete() was asked to remove something that is not a Body Double resource."""


def _marked(text: str | None) -> bool:
    t = (text or "").strip()
    # "bodydouble" (no hyphen) matches the ISO filename bodydouble-forensics.iso
    return TAG in t or "bodydouble" in t or t.startswith("bd-")


def owned(kind: str, item: dict) -> bool:
    if kind == "instance":
        return TAG in (item.get("tags") or []) or (item.get("label") or "").startswith("bd-")
    if kind == "snapshot":
        desc = item.get("description") or ""
        return _marked(desc) and not PROTECTED_SNAPSHOT.search(desc)
    if kind == "firewall":
        desc = (item.get("description") or "").strip()
        if desc.startswith(("bd twin ", "bd quarantine ")):
            # the backend's own groups. An ATTACHED quarantine group is live
            # containment on production: never ours to sweep (B3 run 7 leak)
            return not item.get("instance_count")
        return _marked(desc)
    if kind == "vpc":
        return _marked(item.get("description"))
    if kind in ("object_storage", "nat_gateway", "reserved_ip"):
        return _marked(item.get("label"))
    if kind == "iso":
        return _marked(item.get("filename"))
    return False


def delete(api: Api, kind: str, item: dict, keep: set[str] = frozenset()) -> None:
    if not owned(kind, item) or item["id"] in keep:
        raise RefusedDelete(f"{kind} {item.get('id')} is not a deletable body-double resource")
    path = delete_path(kind, item)
    for attempt in range(8):  # VPC/firewall deletes 4xx until their instances are really gone
        status, _ = api.call("DELETE", path, ok=(400, 404, 409, 412, 422, 500))
        if status < 400 or status == 404:
            return
        time.sleep(15)
    raise RuntimeError(f"could not delete {kind} {item['id']} (last status {status})")


def describe(kind: str, item: dict) -> str:
    name = item.get("label") or item.get("description") or item.get("filename") or ""
    return f"{kind:<8} {item['id']}  {name!r}"


def sweep(api: Api, dry_run: bool, keep: set[str], out=print) -> dict:
    summary = {}
    for kind in ORDER:
        items = list_kind(api, kind)
        mine = [i for i in items if owned(kind, i) and i["id"] not in keep]
        for item in mine:
            out(("would delete " if dry_run else "deleting     ") + describe(kind, item))
            if not dry_run:
                delete(api, kind, item, keep)
        for item in items:
            if item not in mine:
                out("keeping      " + describe(kind, item))
        summary[kind] = {"project": len(mine), "other": len(items) - len(mine)}
    return summary


def burn(api: Api) -> tuple[float, float, int, int]:
    """(compute $/hr, snapshot storage $/hr, instances, snapshots) for what remains."""
    plans = {p["id"]: p for p in api.list_all("/v2/plans", "plans")}
    compute = 0.0
    instances = api.list_all("/v2/instances", "instances")
    for i in instances:
        p = plans.get(i.get("plan"), {})
        compute += p.get("hourly_cost") or (p.get("monthly_cost", 0) / HOURS_PER_MONTH)
    snaps = api.list_all("/v2/snapshots", "snapshots")
    gb = sum((s.get("compressed_size") or s.get("size") or 0) for s in snaps) / 1e9
    storage = gb * SNAPSHOT_USD_PER_GB_MONTH / HOURS_PER_MONTH
    return compute, storage, len(instances), len(snaps)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--include-env-refs", action="store_true",
                    help="also delete the ISO/VPC named by VULTR_ISO_ID/BD_VPC_ID")
    ap.add_argument("--release-reserved-ip", action="store_true",
                    help="also delete the reserved IP in BD_CP_RESERVED_IP_ID (gate FINAL)")
    ap.add_argument("--keep", action="append", default=[], metavar="ID",
                    help="never delete this resource id (repeatable)")
    args = ap.parse_args()
    env = load_secrets()
    keep = set() if args.include_env_refs else {v for k, v in env.items()
                                               if k in ("VULTR_ISO_ID", "BD_VPC_ID") and v}
    if not args.release_reserved_ip and env.get("BD_CP_RESERVED_IP_ID"):
        keep.add(env["BD_CP_RESERVED_IP_ID"])
    shop = REPO / "evals/results/real-mode/S4/result.json"
    if not args.include_env_refs and shop.is_file():  # Gate 1/2: snapshot ef199a06
        keep.add(__import__("json").loads(shop.read_text())["snapshot_id"])
    keep |= set(args.keep)
    api = Api(env["VULTR_API_KEY"])
    summary = sweep(api, args.dry_run, keep)
    if not args.dry_run:
        time.sleep(5)
    compute, storage, n_inst, n_snap = burn(api)
    left = api.list_all("/v2/instances", "instances")
    print(f"project instances left: {sum(owned('instance', i) for i in left)}")
    print(f"summary: {summary}")
    n_nat = len(list_nat_gateways(api))
    print(f"burn: ${compute:.4f}/hr compute ({n_inst} instances on the account); "
          f"snapshot storage ${storage:.4f}/hr ({n_snap} snapshots); "
          f"{n_nat} NAT gateways on the account (billed hourly, not priced here)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
