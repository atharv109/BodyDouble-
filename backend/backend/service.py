"""CaseService: the case state machine. One method per phase of a case; every
mutation goes through the hash-chained case log. The state machine itself is
contracts.models.CASE_TRANSITIONS — this file only walks legal transitions.

Phases are added one per checklist item (F1 open, F2 snapshot, F3 twin,
F4 register/seal, then investigate -> report -> approve -> teardown).
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import re
import secrets
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from contracts.events import ActionApplied, ActionProposed, SealCheck, StateChanged
from contracts.models import (
    Action,
    ActionKind,
    ActionStatus,
    Actor,
    Case,
    CaseState,
    CreateTwinRequest,
    Evidence,
    FirewallRule,
    SealStatus,
    can_transition,
)
from contracts.vultr import VultrError, VultrNotFound

from .db import ActionRow, CaseRow, EvidenceRow, FindingRow, ReportRow, utcnow
from .fake_twin import fake_twin_loop

log = logging.getLogger("backend")

# Vultr instance ids: the charset ALLOWED_RAW_CALLS already assumes
_INSTANCE_ID = re.compile(r"^[A-Za-z0-9-]{1,64}$")


class CaseNotFound(LookupError):
    pass


class CaseFailure(Exception):
    """Something in the run failed; the case goes to `failed` (teardown runs)."""


class TransitionError(ValueError):
    def __init__(self, src: CaseState, dst: CaseState):
        super().__init__(f"illegal transition {src.value} -> {dst.value}")
        self.src, self.dst = src, dst


class ActionConflict(ValueError):
    """The action is not in `proposed` any more (approved twice, etc.)."""


class CaseService:
    def __init__(self, state):
        self.state = state
        self.settings = state.settings
        self.vultr = state.vultr
        self.log = state.log
        self.channel = state.channel

    # ------------------------------------------------------------- helpers
    def row(self, case_id: str) -> CaseRow:
        with self.state.sf() as s:
            r = s.get(CaseRow, case_id)
            if r is None:
                raise CaseNotFound(case_id)
            return r

    def _save(self, row: CaseRow) -> None:
        with self.state.sf() as s:
            s.merge(row)
            s.commit()

    def model(self, case_id: str) -> Case:
        return self.row(case_id).to_model()

    def _move(self, row: CaseRow, dst: CaseState, detail: str = "",
              actor: Actor = Actor.system) -> CaseState:
        src = CaseState(row.state)
        if not can_transition(src, dst):
            raise TransitionError(src, dst)
        row.state = dst.value
        self._save(row)
        self.log.append(row.id, "state_changed",
                        StateChanged(case_id=row.id, from_state=src, to_state=dst, detail=detail),
                        actor=actor)
        return src

    def _touch(self, row: CaseRow) -> None:  # persist column updates
        self._save(row)

    def next_case_id(self) -> str:
        with self.state.sf() as s:
            rows = s.execute(select(CaseRow.id).order_by(CaseRow.id.desc()).limit(1)).scalars().all()
        if not rows or not rows[0].startswith("case-"):
            return "case-0001"
        try:
            return f"case-{int(rows[0].rsplit('-', 1)[1]) + 1:04d}"
        except ValueError:
            return "case-0001"

    # ------------------------------------------------------------- F1: open
    async def open_case(self, instance_id: str, reason: str, operator: str = "operator") -> Case:
        if not _INSTANCE_ID.fullmatch(instance_id):
            raise ValueError("instance_id must be 1-64 chars of [A-Za-z0-9-]")
        try:
            instance = await self.vultr.get_instance(instance_id)
        except VultrNotFound as e:
            raise LookupError(f"unknown instance {instance_id}") from e
        row = None
        for _ in range(5):  # concurrent opens may race on next_case_id; retry
            row = CaseRow(
                id=self.next_case_id(), instance_id=instance_id, instance_label=instance.label,
                reason=reason, state=CaseState.opened.value, created_at=utcnow(),
                operator=operator,
            )
            with self.state.sf() as s:
                s.add(row)
                try:
                    s.commit()
                except IntegrityError:
                    continue
                s.expunge(row)
            break
        else:
            raise CaseFailure("could not allocate a case id")
        self.log.append(row.id, "state_changed",
                        StateChanged(case_id=row.id, from_state=None,
                                     to_state=CaseState.opened,
                                     detail="opened by operator"),
                        actor=Actor.human)
        return row.to_model()

    async def run_case(self, case_id: str) -> Case:
        """Walk the case as far as the phases implemented so far allow."""
        row = self.row(case_id)
        try:
            await self._snapshot_phase(row)
            await self._twin_phase(row)
        except CaseFailure as e:
            await self.fail_case(case_id, str(e))
        except VultrError as e:
            log.exception("vultr error in case %s", case_id)
            await self.fail_case(case_id, f"Vultr API {e.status_code} error")
        except VultrNotFound as e:
            await self.fail_case(case_id, f"resource vanished mid-case: {e}")
        except Exception as e:  # security review: never strand a live twin
            log.exception("unexpected error in case %s", case_id)
            await self.fail_case(case_id, f"unexpected {type(e).__name__}: {e}")
        return self.model(case_id)

    # ------------------------------------------------------------- F2: snapshot
    async def _snapshot_phase(self, row: CaseRow) -> None:
        self._move(row, CaseState.snapshotting, "snapshot requested")
        snap = await self.vultr.create_snapshot(
            row.instance_id, f"body-double case {row.id}")
        row.snapshot_id = snap.id
        self._touch(row)
        self.log.append(row.id, "snapshot_created",
                        {"snapshot_id": snap.id, "instance_id": row.instance_id})
        deadline = utcnow() + timedelta(seconds=self.settings.snapshot_timeout_s)
        while True:
            snap = await self.vultr.get_snapshot(snap.id)
            if snap.status == "complete":
                break
            if utcnow() > deadline:
                raise CaseFailure(f"snapshot {snap.id} did not complete in time")
            await asyncio.sleep(self.settings.poll_interval_s)
        # evidence item #1: the snapshot itself (PRD "Preserve")
        self._add_evidence(Evidence(
            id=self._next_id(EvidenceRow, row.id, "ev"), case_id=row.id, step_id=None,
            path=f"snapshot:{snap.id}", sha256=hashlib.sha256(snap.id.encode()).hexdigest(),
            excerpt=f"Vultr snapshot {snap.id} of {row.instance_id} at "
                    f"{utcnow().isoformat()}Z",
        ))

    def _add_evidence(self, evidence: Evidence) -> Evidence:
        with self.state.sf() as s:
            s.add(EvidenceRow(
                id=evidence.id, case_id=evidence.case_id, step_id=evidence.step_id,
                path=evidence.path, sha256=evidence.sha256, excerpt=evidence.excerpt,
                injection_flag=evidence.injection_flag))
            s.commit()
        self.log.append(evidence.case_id, "evidence_added", evidence.model_dump(mode="json"))
        return evidence

    # ------------------------------------------------------------- F3: twin
    async def _twin_phase(self, row: CaseRow) -> None:
        """Build the twin: dedicated VPC, inbound-deny firewall group (a group
        with no allow rules), and an instance restored from the snapshot
        booting the forensics ISO — snapshot_id + iso_id in one create call, or
        create + attach_iso when Vultr rejects the combination (day-one test
        T1, settings.t1_fallback; on by default in real mode)."""
        self._move(row, CaseState.restoring, f"building twin from snapshot {row.snapshot_id}")
        source = await self.vultr.get_instance(row.instance_id)
        vpc = await self.vultr.create_vpc(source.region, f"body-double twin {row.id}")
        fw = await self.vultr.create_firewall_group(f"bd twin {row.id} inbound deny")
        row.vpc_id, row.firewall_group_id = vpc.id, fw.id
        row.vpc_subnet, row.vpc_mask = vpc.v4_subnet, vpc.v4_subnet_mask
        self._touch(row)
        req = CreateTwinRequest(
            region=source.region, plan=self.settings.twin_plan, label=f"bd-twin-{row.id}",
            snapshot_id=row.snapshot_id,
            iso_id=None if self.settings.t1_fallback else self.settings.iso_id,
            attach_vpc=[vpc.id], firewall_group_id=fw.id)
        try:
            twin = await self.vultr.create_instance(req)
            iso_in_create = req.iso_id is not None
        except VultrError as e:
            # Vultr rejected snapshot_id + iso_id in one call (day-one test T1):
            # per the PRD, fall back to create-from-snapshot + attach_iso
            if self.settings.t1_fallback or e.status_code != 400:
                raise
            twin = await self.vultr.create_instance(req.model_copy(update={"iso_id": None}))
            iso_in_create = False
        # persist the twin id before anything else can fail on it: teardown
        # (F11) must always know the live instance (security review)
        row.twin_instance_id = twin.id
        self._touch(row)
        if not iso_in_create:
            # attach right after create, before any boot polling. On real
            # Vultr the instance may already be booting in this window — see
            # the day-one T1 decision (halt/attach/boot needs a contracts call).
            await self.vultr.attach_iso(twin.id, self.settings.iso_id)
        self.log.append(row.id, "twin_created", {
            "twin_instance_id": twin.id, "vpc_id": vpc.id, "firewall_group_id": fw.id,
            "iso_id": self.settings.iso_id, "iso_attached_in_create": iso_in_create})
        # F4: one-time registration token, consumed at first register. FakeVultr
        # mode hands it to the in-process twin stand-in; real mode delivers it
        # to the ISO (delivery mechanism is the orchestrator's day-one call).
        token = "twreg-" + secrets.token_urlsafe(24)
        row.reg_token = token
        self._touch(row)
        self.channel.prepare_registration(row.id, token)
        if self.state.is_fake and self.settings.spawn_fake_twin:
            self.state.fake_twin_tasks[row.id] = asyncio.create_task(
                fake_twin_loop(self.state, row.id, token, twin.internal_ip))
        deadline = utcnow() + timedelta(seconds=self.settings.boot_timeout_s)
        while True:
            twin = await self.vultr.get_instance(twin.id)
            if twin.status == "active":
                break
            if utcnow() > deadline:
                raise CaseFailure(f"twin {twin.id} did not boot in time")
            await asyncio.sleep(self.settings.poll_interval_s)
        # the twin checked in over the VPC and both seal checks passed (F4/F5)
        try:
            ok, reason = await asyncio.wait_for(
                self.channel.wait_registered(row.id),
                timeout=self.settings.register_timeout_s)
        except (TimeoutError, asyncio.TimeoutError):
            raise CaseFailure(f"twin {row.twin_instance_id} did not register in time")
        if not ok:
            raise CaseFailure(f"twin did not seal: {reason}")
        row = self.row(row.id)  # register() wrote seal/token/ip in its own session
        seal = SealStatus.model_validate(row.seal)
        for check, passed in (("disk_read_only", seal.disk_read_only),
                              ("egress_blocked", seal.egress_blocked)):
            self.log.append(row.id, "seal_check", SealCheck(
                case_id=row.id, check=check, passed=passed,
                output=seal.detail.get(check, "")))
        self._move(row, CaseState.sealed, "twin sealed: disk read-only, egress blocked")

    # ------------------------------------------------------------- F9: actions
    async def build_action_menu(self, case_id: str) -> list[Action]:
        """Containment menu built by code, never the model (PRD rows):
        findings propose quarantine + halt; the report adds the human-run SSH
        and secrets entries. Every action is inert data until approved."""
        row = self.row(case_id)
        with self.state.sf() as s:
            report = s.get(ReportRow, case_id)
            has_findings = bool(s.scalar(
                select(func.count()).where(FindingRow.case_id == case_id)))
            existing = {ActionKind(k) for k in s.execute(
                select(ActionRow.kind).where(ActionRow.case_id == case_id)).scalars()}

        desired: list[ActionKind] = []
        if has_findings:
            desired += [ActionKind.quarantine_firewall, ActionKind.stop_instance]
            if report is not None and report.rogue_ssh_keys:
                desired.append(ActionKind.revoke_ssh_key)
            if report is not None and report.secrets_found:
                desired.append(ActionKind.rotate_secrets)

        for kind in [k for k in desired if k not in existing]:
            await self._propose_action(row, kind, report)
        with self.state.sf() as s:
            rows = list(s.execute(select(ActionRow)
                                  .where(ActionRow.case_id == case_id)
                                  .order_by(ActionRow.id)).scalars())
        return [r.to_model() for r in rows]

    async def _propose_action(self, row: CaseRow, kind: ActionKind,
                              report: ReportRow | None) -> None:
        target = row.instance_id
        if kind is ActionKind.quarantine_firewall:
            if row.quarantine_group_id is None:
                group = await self.vultr.create_firewall_group(
                    f"bd quarantine {row.id}")
                await self.vultr.add_firewall_rule(group.id, FirewallRule(
                    protocol="tcp", subnet=self.settings.admin_ip, subnet_size=32,
                    port="22", notes="admin SSH only"))
                row.quarantine_group_id = group.id
                self._touch(row)
            action = Action(
                id=self._next_id(ActionRow, row.id, "act"), case_id=row.id, kind=kind,
                target=target, api_method="PATCH", api_path=f"/v2/instances/{target}",
                api_body={"firewall_group_id": row.quarantine_group_id},
                description=f"Move {row.instance_label} into the quarantine "
                            f"group (admin SSH only)")
        elif kind is ActionKind.stop_instance:
            action = Action(
                id=self._next_id(ActionRow, row.id, "act"), case_id=row.id, kind=kind,
                target=target, api_method="POST",
                api_path=f"/v2/instances/{target}/halt",
                description=f"Halt {row.instance_label}")
        elif kind is ActionKind.revoke_ssh_key:
            keys = "; ".join(report.rogue_ssh_keys)
            action = Action(
                id=self._next_id(ActionRow, row.id, "act"), case_id=row.id, kind=kind,
                target=target, api_method=None, api_path=None,
                description=f"On {row.instance_label}, remove the rogue "
                            f"authorized_keys lines: {keys}")
        else:  # rotate_secrets
            paths = ", ".join(report.secrets_found)
            action = Action(
                id=self._next_id(ActionRow, row.id, "act"), case_id=row.id, kind=kind,
                target=target, api_method=None, api_path=None,
                description=f"Rotate the secrets found on the disk: {paths}")
        with self.state.sf() as s:
            s.add(ActionRow(**action.model_dump()))
            s.commit()
        self.log.append(row.id, "action_proposed", ActionProposed(action=action),
                        actor=Actor.agent)

    def _next_id(self, row_class, case_id: str, prefix: str) -> str:
        with self.state.sf() as s:
            n = s.scalar(select(func.count()).where(row_class.case_id == case_id)) or 0
        return f"{case_id}-{prefix}-{n + 1:03d}"

    async def approve_action(self, case_id: str, action_id: str, operator: str) -> Action:
        with self.state.sf() as s:
            row = s.get(ActionRow, action_id)
            if row is None or row.case_id != case_id:
                raise LookupError(f"unknown action {action_id}")
            if row.status != ActionStatus.proposed.value:
                raise ActionConflict(f"action is {row.status}, not proposed")
            row.status = ActionStatus.approved.value
            row.approved_by = operator
            s.commit()
            model = row.to_model()
        self.log.append(case_id, "action_approved",
                        {"action_id": action_id, "approved_by": operator},
                        actor=Actor.human)
        return model

    async def apply_action(self, case_id: str, action_id: str) -> Action:
        """F10: execute an approved action against production and log the exact
        API response. No-API kinds (human-run) are marked applied outright."""
        with self.state.sf() as s:
            row = s.get(ActionRow, action_id)
            if row is None or row.case_id != case_id:
                raise LookupError(f"unknown action {action_id}")
            if row.status != ActionStatus.approved.value:
                raise ActionConflict(f"action is {row.status}, not approved")
        if row.api_method:
            api = await self.vultr.request(row.api_method, row.api_path, row.api_body)
            status = (ActionStatus.applied if 200 <= api.status_code < 300
                      else ActionStatus.rejected)
        else:
            api, status = None, ActionStatus.applied
        with self.state.sf() as s:
            row = s.get(ActionRow, action_id)
            row.status = status.value
            row.response = api.model_dump(mode="json") if api else None
            s.commit()
            model = row.to_model()
        self.log.append(case_id, "action_applied", ActionApplied(action=model, api=api))
        return model

    async def fail_case(self, case_id: str, reason: str) -> None:
        row = self.row(case_id)
        if CaseState(row.state) in (CaseState.closed, CaseState.failed):
            return
        # teardown runs in try/finally so the twin never outlives the case (F11)
        try:
            pass  # teardown is added with F11
        finally:
            if can_transition(CaseState(row.state), CaseState.failed):
                self._move(row, CaseState.failed, reason)
            self.channel.cleanup_case(case_id)
