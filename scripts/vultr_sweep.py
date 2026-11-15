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
Resources the secrets file points at (VULTR_ISO_ID, BD_VPC_ID) are kept unless
--include-env-refs is given: they cost $0/hr and the app needs them.
delete() re-checks owned() itself, so nothing else can be deleted by mistake.
"""
from __future__ import annotations

import argparse
import re
import sys
import time

sys.path.insert(0, __import__("os").path.dirname(__file__))
from bdvultr import Api, load_secrets  # noqa: E402

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
}
ORDER = ["instance", "snapshot", "firewall", "vpc", "object_storage", "iso"]  # instances first


class RefusedDelete(Exception):
    """delete() was asked to remove something that is not a Body Double resource."""


def _marked(text: str | None) -> bool:
    t = (text or "").strip()
    return TAG in t or t.startswith("bd-")


def owned(kind: str, item: dict) -> bool:
    if kind == "instance":
        return TAG in (item.get("tags") or []) or (item.get("label") or "").startswith("bd-")
    if kind == "snapshot":
        desc = item.get("description") or ""
        return _marked(desc) and not PROTECTED_SNAPSHOT.search(desc)
    if kind in ("firewall", "vpc"):
        return _marked(item.get("description"))
    if kind == "object_storage":
        return _marked(item.get("label"))
    if kind == "iso":
        return _marked(item.get("filename"))
    return False


def delete(api: Api, kind: str, item: dict, keep: set[str] = frozenset()) -> None:
    if not owned(kind, item) or item["id"] in keep:
        raise RefusedDelete(f"{kind} {item.get('id')} is not a deletable body-double resource")
    path = f"{KINDS[kind][2]}/{item['id']}"
    for attempt in range(8):  # VPC/firewall deletes 4xx until their instances are really gone
        status, _ = api.call("DELETE", path, ok=(400, 404, 409, 412, 500))
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
        path, key, _ = KINDS[kind]
        items = api.list_all(path, key)
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
    args = ap.parse_args()
    env = load_secrets()
    keep = set() if args.include_env_refs else {v for k, v in env.items()
                                               if k in ("VULTR_ISO_ID", "BD_VPC_ID") and v}
    api = Api(env["VULTR_API_KEY"])
    summary = sweep(api, args.dry_run, keep)
    if not args.dry_run:
        time.sleep(5)
    compute, storage, n_inst, n_snap = burn(api)
    left = api.list_all("/v2/instances", "instances")
    print(f"project instances left: {sum(owned('instance', i) for i in left)}")
    print(f"summary: {summary}")
    print(f"burn: ${compute:.4f}/hr compute ({n_inst} instances on the account); "
          f"snapshot storage ${storage:.4f}/hr ({n_snap} snapshots)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
