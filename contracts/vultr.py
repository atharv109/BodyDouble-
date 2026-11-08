"""VultrClient interface + FakeVultr (tests, demo replay) + RealVultr (api.vultr.com/v2).

Only the control plane holds a VultrClient. Every path below must be confirmed
against the live Vultr API on day one (PRD: day-one tests T1-T4).
"""
from __future__ import annotations

import itertools
import re
from typing import Any, Protocol

import httpx

from .models import (
    ApiResponse,
    CreateTwinRequest,
    FirewallRule,
    VultrFirewallGroup,
    VultrInstance,
    VultrSnapshot,
    VultrVPC,
)


# The only raw calls request() will send: the PRD containment menu. Anything else is
# refused before it leaves the process, so the API key can't go to another host.
ALLOWED_RAW_CALLS: list[tuple[str, re.Pattern[str]]] = [
    ("PATCH", re.compile(r"/v2/instances/[A-Za-z0-9-]{1,64}")),  # quarantine_firewall
    ("POST", re.compile(r"/v2/instances/[A-Za-z0-9-]{1,64}/halt")),  # stop_instance
]
ALLOWED_PATCH_KEYS = {"firewall_group_id"}


class DisallowedCall(Exception):
    """request() refused a (method, path, body) outside ALLOWED_RAW_CALLS."""


def check_raw_call(method: str, path: str, body: dict | None) -> None:
    if not any(method == m and p.fullmatch(path) for m, p in ALLOWED_RAW_CALLS):
        raise DisallowedCall(f"{method} {path}")
    if method == "PATCH" and (not body or set(body) - ALLOWED_PATCH_KEYS):
        raise DisallowedCall(f"PATCH body keys {sorted(body or {})}")


class VultrNotFound(Exception):
    """Resource returned 404. Teardown (F11) treats this as success."""


class VultrError(Exception):
    def __init__(self, status_code: int, body: Any):
        super().__init__(f"Vultr API {status_code}: {body}")
        self.status_code = status_code
        self.body = body


class VultrClient(Protocol):
    async def list_instances(self) -> list[VultrInstance]: ...
    async def get_instance(self, instance_id: str) -> VultrInstance: ...  # raises VultrNotFound
    async def create_snapshot(self, instance_id: str, description: str) -> VultrSnapshot: ...
    async def get_snapshot(self, snapshot_id: str) -> VultrSnapshot: ...
    async def create_vpc(self, region: str, description: str) -> VultrVPC: ...
    async def delete_vpc(self, vpc_id: str) -> None: ...
    async def create_firewall_group(self, description: str) -> VultrFirewallGroup: ...
    async def add_firewall_rule(self, group_id: str, rule: FirewallRule) -> None: ...
    async def delete_firewall_group(self, group_id: str) -> None: ...
    async def create_instance(self, req: CreateTwinRequest) -> VultrInstance: ...
    async def attach_iso(self, instance_id: str, iso_id: str) -> None: ...
    async def restore_snapshot(self, instance_id: str, snapshot_id: str) -> None: ...  # T1 fallback
    async def delete_instance(self, instance_id: str) -> None: ...

    async def request(self, method: str, path: str, body: dict | None = None) -> ApiResponse:
        """Raw call used to apply an approved Action verbatim (F10). Raises
        DisallowedCall unless (method, path, body) passes check_raw_call. Never
        raises on HTTP errors; the status code is returned and logged."""
        ...


# =================================================================== FakeVultr
class FakeVultr:
    """In-memory Vultr. Deterministic ids. Snapshots complete after
    `snapshot_polls` get_snapshot calls; new instances turn active after
    `instance_polls` get_instance calls. `calls` records every call for assertions.
    `reject_snapshot_plus_iso=True` mimics a T1 failure."""

    SHOP_PROD = "inst-shop-prod"
    CLEAN_CONTROL = "inst-clean-control"

    def __init__(self, snapshot_polls: int = 2, instance_polls: int = 2,
                 reject_snapshot_plus_iso: bool = False):
        self.snapshot_polls = snapshot_polls
        self.instance_polls = instance_polls
        self.reject_snapshot_plus_iso = reject_snapshot_plus_iso
        self._ids = itertools.count(1)
        self.calls: list[tuple[str, str, dict | None]] = []
        self.instances: dict[str, VultrInstance] = {
            self.SHOP_PROD: VultrInstance(
                id=self.SHOP_PROD, label="shop-prod", region="ewr", main_ip="45.77.10.20",
                status="active", plan="vc2-1c-2gb", os="Ubuntu 24.04 LTS x64",
                firewall_group_id="fw-shop-web"),
            self.CLEAN_CONTROL: VultrInstance(
                id=self.CLEAN_CONTROL, label="clean-control", region="ewr", main_ip="45.77.10.21",
                status="active", plan="vc2-1c-2gb", os="Ubuntu 24.04 LTS x64",
                firewall_group_id="fw-shop-web"),
        }
        self.snapshots: dict[str, VultrSnapshot] = {}
        self.vpcs: dict[str, VultrVPC] = {}
        self.firewall_groups: dict[str, VultrFirewallGroup] = {
            "fw-shop-web": VultrFirewallGroup(id="fw-shop-web", description="shop web 80/443/22"),
        }
        self.firewall_rules: dict[str, list[FirewallRule]] = {"fw-shop-web": []}
        self.isos: dict[str, str] = {}  # instance_id -> iso_id
        self._polls: dict[str, int] = {}

    def _id(self, prefix: str) -> str:
        return f"{prefix}-{next(self._ids):04d}"

    def _log(self, method: str, path: str, body: dict | None = None) -> None:
        self.calls.append((method, path, body))

    def _get(self, store: dict, key: str):
        if key not in store:
            raise VultrNotFound(key)
        return store[key]

    async def list_instances(self) -> list[VultrInstance]:
        self._log("GET", "/v2/instances")
        return list(self.instances.values())

    async def get_instance(self, instance_id: str) -> VultrInstance:
        self._log("GET", f"/v2/instances/{instance_id}")
        inst = self._get(self.instances, instance_id)
        if inst.status == "pending":
            self._polls[instance_id] = self._polls.get(instance_id, 0) + 1
            if self._polls[instance_id] >= self.instance_polls:
                inst.status = "active"
        return inst.model_copy()

    async def create_snapshot(self, instance_id: str, description: str) -> VultrSnapshot:
        self._log("POST", "/v2/snapshots", {"instance_id": instance_id, "description": description})
        self._get(self.instances, instance_id)
        snap = VultrSnapshot(id=self._id("snap"), description=description, status="pending",
                             size=25 * 1024**3, date_created="2026-11-07T07:00:00+00:00")
        self.snapshots[snap.id] = snap
        return snap.model_copy()

    async def get_snapshot(self, snapshot_id: str) -> VultrSnapshot:
        self._log("GET", f"/v2/snapshots/{snapshot_id}")
        snap = self._get(self.snapshots, snapshot_id)
        self._polls[snapshot_id] = self._polls.get(snapshot_id, 0) + 1
        if self._polls[snapshot_id] >= self.snapshot_polls:
            snap.status = "complete"
        return snap.model_copy()

    async def create_vpc(self, region: str, description: str) -> VultrVPC:
        self._log("POST", "/v2/vpcs", {"region": region, "description": description})
        n = len(self.vpcs) + 1
        vpc = VultrVPC(id=self._id("vpc"), region=region, description=description,
                       v4_subnet=f"10.{n}.96.0", v4_subnet_mask=24)
        self.vpcs[vpc.id] = vpc
        return vpc.model_copy()

    async def delete_vpc(self, vpc_id: str) -> None:
        self._log("DELETE", f"/v2/vpcs/{vpc_id}")
        self._get(self.vpcs, vpc_id)
        del self.vpcs[vpc_id]

    async def create_firewall_group(self, description: str) -> VultrFirewallGroup:
        self._log("POST", "/v2/firewalls", {"description": description})
        g = VultrFirewallGroup(id=self._id("fw"), description=description)
        self.firewall_groups[g.id] = g
        self.firewall_rules[g.id] = []
        return g.model_copy()

    async def add_firewall_rule(self, group_id: str, rule: FirewallRule) -> None:
        self._log("POST", f"/v2/firewalls/{group_id}/rules", rule.model_dump())
        self._get(self.firewall_groups, group_id)
        self.firewall_rules[group_id].append(rule)

    async def delete_firewall_group(self, group_id: str) -> None:
        self._log("DELETE", f"/v2/firewalls/{group_id}")
        self._get(self.firewall_groups, group_id)
        del self.firewall_groups[group_id]

    async def create_instance(self, req: CreateTwinRequest) -> VultrInstance:
        body = req.model_dump(exclude_none=True)
        self._log("POST", "/v2/instances", body)
        if self.reject_snapshot_plus_iso and req.iso_id and req.snapshot_id:
            raise VultrError(400, {"error": "Only one of os_id, iso_id, snapshot_id may be set"})
        if req.snapshot_id:
            self._get(self.snapshots, req.snapshot_id)
        vpc =self.vpcs.get(req.attach_vpc[0]) if req.attach_vpc else None
        inst = VultrInstance(
            id=self._id("inst"), label=req.label, region=req.region, main_ip="149.28.0.99",
            internal_ip=(vpc.v4_subnet.rsplit(".", 1)[0] + ".3") if vpc else "",
            status="pending", plan=req.plan, os="Snapshot" if req.snapshot_id else "Custom ISO",
            firewall_group_id=req.firewall_group_id, vpc_ids=list(req.attach_vpc))
        self.instances[inst.id] = inst
        if req.iso_id:
            self.isos[inst.id] = req.iso_id
        return inst.model_copy()

    async def attach_iso(self, instance_id: str, iso_id: str) -> None:
        self._log("POST", f"/v2/instances/{instance_id}/iso/attach", {"iso_id": iso_id})
        self._get(self.instances, instance_id)
        self.isos[instance_id] = iso_id

    async def restore_snapshot(self, instance_id: str, snapshot_id: str) -> None:
        self._log("POST", f"/v2/instances/{instance_id}/restore", {"snapshot_id": snapshot_id})
        inst = self._get(self.instances, instance_id)
        self._get(self.snapshots, snapshot_id)
        inst.os, inst.status = "Snapshot", "pending"  # ISO stays attached, so it boots first

    async def delete_instance(self, instance_id: str) -> None:
        self._log("DELETE", f"/v2/instances/{instance_id}")
        self._get(self.instances, instance_id)
        del self.instances[instance_id]
        self.isos.pop(instance_id, None)

    async def request(self, method: str, path: str, body: dict | None = None) -> ApiResponse:
        """Supports the two production-changing action calls from the PRD menu."""
        check_raw_call(method, path, body)
        self._log(method, path, body)
        parts = path.strip("/").split("/")  # v2 instances {id} [halt]
        if len(parts) >= 3 and parts[:2] == ["v2", "instances"] and parts[2] in self.instances:
            inst = self.instances[parts[2]]
            if method == "PATCH" and len(parts) == 3:
                if body and "firewall_group_id" in body:
                    if body["firewall_group_id"] not in self.firewall_groups:
                        return ApiResponse(method=method, path=path, body=body, status_code=400,
                                           response={"error": "invalid firewall group"})
                    inst.firewall_group_id = body["firewall_group_id"]
                return ApiResponse(method=method, path=path, body=body, status_code=202,
                                   response={"instance": inst.model_dump()})
            if method == "POST" and len(parts) == 4 and parts[3] == "halt":
                inst.power_status = "stopped"
                return ApiResponse(method=method, path=path, body=body, status_code=204, response=None)
        return ApiResponse(method=method, path=path, body=body, status_code=404,
                           response={"error": "Not found"})


# =================================================================== RealVultr
class RealVultr:
    """Thin async client for https://api.vultr.com/v2. Holds the API key; only the
    control plane may construct one."""

    BASE = "https://api.vultr.com"

    def __init__(self, api_key: str, base_url: str = BASE, timeout: float = 30.0):
        self._http = httpx.AsyncClient(
            base_url=base_url, timeout=timeout, follow_redirects=False,
            headers={"Authorization": f"Bearer {api_key}"})

    async def aclose(self) -> None:
        await self._http.aclose()

    async def _call(self, method: str, path: str, body: dict | None = None) -> Any:
        r = await self._http.request(method, path, json=body)
        if r.status_code == 404:
            raise VultrNotFound(path)
        if r.status_code >= 400:
            raise VultrError(r.status_code, r.text)
        return r.json() if r.content else None

    async def list_instances(self) -> list[VultrInstance]:
        out, cursor = [], ""
        while True:
            data = await self._call("GET", f"/v2/instances?per_page=100&cursor={cursor}")
            out += [VultrInstance.model_validate(i) for i in data["instances"]]
            cursor = data.get("meta", {}).get("links", {}).get("next", "")
            if not cursor:
                return out

    async def get_instance(self, instance_id: str) -> VultrInstance:
        return VultrInstance.model_validate((await self._call("GET", f"/v2/instances/{instance_id}"))["instance"])

    async def create_snapshot(self, instance_id: str, description: str) -> VultrSnapshot:
        data = await self._call("POST", "/v2/snapshots", {"instance_id": instance_id, "description": description})
        return VultrSnapshot.model_validate(data["snapshot"])

    async def get_snapshot(self, snapshot_id: str) -> VultrSnapshot:
        return VultrSnapshot.model_validate((await self._call("GET", f"/v2/snapshots/{snapshot_id}"))["snapshot"])

    async def create_vpc(self, region: str, description: str) -> VultrVPC:
        data = await self._call("POST", "/v2/vpcs", {"region": region, "description": description})
        return VultrVPC.model_validate(data["vpc"])

    async def delete_vpc(self, vpc_id: str) -> None:
        await self._call("DELETE", f"/v2/vpcs/{vpc_id}")

    async def create_firewall_group(self, description: str) -> VultrFirewallGroup:
        data = await self._call("POST", "/v2/firewalls", {"description": description})
        return VultrFirewallGroup.model_validate(data["firewall_group"])

    async def add_firewall_rule(self, group_id: str, rule: FirewallRule) -> None:
        await self._call("POST", f"/v2/firewalls/{group_id}/rules", rule.model_dump())

    async def delete_firewall_group(self, group_id: str) -> None:
        await self._call("DELETE", f"/v2/firewalls/{group_id}")

    async def create_instance(self, req: CreateTwinRequest) -> VultrInstance:
        data = await self._call("POST", "/v2/instances", req.model_dump(exclude_none=True))
        return VultrInstance.model_validate(data["instance"])

    async def attach_iso(self, instance_id: str, iso_id: str) -> None:
        await self._call("POST", f"/v2/instances/{instance_id}/iso/attach", {"iso_id": iso_id})

    async def restore_snapshot(self, instance_id: str, snapshot_id: str) -> None:
        await self._call("POST", f"/v2/instances/{instance_id}/restore", {"snapshot_id": snapshot_id})

    async def delete_instance(self, instance_id: str) -> None:
        await self._call("DELETE", f"/v2/instances/{instance_id}")

    async def request(self, method: str, path: str, body: dict | None = None) -> ApiResponse:
        check_raw_call(method, path, body)
        r = await self._http.request(method, path, json=body)
        try:
            payload = r.json() if r.content else None
        except ValueError:
            payload = r.text
        return ApiResponse(method=method, path=path, body=body, status_code=r.status_code, response=payload)
