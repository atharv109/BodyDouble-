"""S1 guard tests: the sweep must never delete anything that is not ours."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent))
import vultr_sweep as vs  # noqa: E402
from bdvultr import Api  # noqa: E402

STATE = {
    "instances": [
        {"id": "i-ours", "label": "shop-prod", "tags": ["body-double"], "plan": "vc2-1c-1gb"},
        {"id": "i-bd", "label": "bd-twin-1", "tags": [], "plan": "vc2-1c-1gb"},
        {"id": "i-theirs", "label": "customer-db", "tags": ["prod"], "plan": "vc2-1c-1gb"},
    ],
    "snapshots": [
        {"id": "s-ours", "description": "body-double shop-prod planted", "size": 25e9},
        {"id": "s-case1", "description": "body-double case case-0001", "size": 25e9},
        {"id": "s-case2", "description": "body-double case case-0002", "size": 25e9},
        {"id": "s-theirs", "description": "nightly backup", "size": 25e9},
    ],
    "firewall_groups": [{"id": "f-ours", "description": "bd-twin-fw"},
                        {"id": "f-theirs", "description": "web"}],
    "vpcs": [{"id": "v-ours", "description": "bd-vpc"}, {"id": "v-env", "description": "bd-shared"},
             {"id": "v-theirs", "description": "office"}],
    "isos": [{"id": "iso-ours", "filename": "bd-forensics.iso"},
             {"id": "iso-theirs", "filename": "windows.iso"}],
    "plans": [{"id": "vc2-1c-1gb", "monthly_cost": 5}],
}


@pytest.fixture
def fake():
    state = json.loads(json.dumps(STATE))
    deleted: list[str] = []
    key_for = {"instances": "instances", "snapshots": "snapshots", "firewalls": "firewall_groups",
               "vpcs": "vpcs", "iso": "isos", "plans": "plans"}

    def handler(req: httpx.Request) -> httpx.Response:
        parts = req.url.path.strip("/").split("/")  # ["v2", kind, id?]
        key = key_for[parts[1]]
        if req.method == "GET":
            return httpx.Response(200, json={key: state[key], "meta": {"links": {"next": ""}}})
        if req.method == "DELETE":
            deleted.append(parts[2])
            state[key] = [i for i in state[key] if i["id"] != parts[2]]
            return httpx.Response(204)
        return httpx.Response(405)

    api = Api("test-key", transport=httpx.MockTransport(handler))
    return api, deleted


def test_sweep_deletes_only_ours(fake):
    api, deleted = fake
    vs.sweep(api, dry_run=False, keep={"v-env"}, out=lambda *_: None)
    assert sorted(deleted) == ["f-ours", "i-bd", "i-ours", "iso-ours", "s-ours", "v-ours"]


def test_case_snapshots_and_env_refs_survive(fake):
    api, deleted = fake
    vs.sweep(api, dry_run=False, keep={"v-env"}, out=lambda *_: None)
    for never in ("s-case1", "s-case2", "v-env", "i-theirs", "s-theirs", "f-theirs",
                  "v-theirs", "iso-theirs"):
        assert never not in deleted


@pytest.mark.parametrize("kind,item", [
    ("instance", STATE["instances"][2]),
    ("snapshot", STATE["snapshots"][1]),   # case-0001: tagged body-double but protected
    ("snapshot", STATE["snapshots"][3]),
    ("firewall", STATE["firewall_groups"][1]),
    ("vpc", STATE["vpcs"][2]),
    ("iso", STATE["isos"][1]),
])
def test_delete_guard_refuses_foreign(fake, kind, item):
    api, deleted = fake
    with pytest.raises(vs.RefusedDelete):
        vs.delete(api, kind, item)
    assert deleted == []


def test_delete_guard_refuses_kept_env_ref(fake):
    api, deleted = fake
    with pytest.raises(vs.RefusedDelete):
        vs.delete(api, "vpc", STATE["vpcs"][1], keep={"v-env"})
    assert deleted == []


def test_dry_run_deletes_nothing(fake):
    api, deleted = fake
    vs.sweep(api, dry_run=True, keep=set(), out=lambda *_: None)
    assert deleted == []


def test_burn_counts_remaining_instances(fake):
    api, _ = fake
    compute, storage, n_inst, n_snap = vs.burn(api)
    assert n_inst == 3 and n_snap == 4
    assert compute == pytest.approx(3 * 5 / 730)
    assert storage == pytest.approx(100 * 0.05 / 730)
