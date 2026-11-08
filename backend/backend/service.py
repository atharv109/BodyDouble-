"""CaseService: the case state machine. One method per phase of a case; every
mutation goes through the hash-chained case log. The state machine itself is
contracts.models.CASE_TRANSITIONS — this file only walks legal transitions.

Phases are added one per checklist item (F1 open, F2 snapshot, F3 twin,
F4 register/seal, then investigate -> report -> approve -> teardown).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import ipaddress
import json
import logging
import re
import secrets
import zipfile
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from contracts.events import (
    ActionApplied,
    ActionProposed,
    SealCheck,
    StateChanged,
    TeardownDone,
)
from contracts.models import (
    Action,
    ActionKind,
    ActionStatus,
    Actor,
    Case,
    CaseDetail,
    CaseState,
    CreateTwinRequest,
    CustomActionRequest,
    Evidence,
    FirewallRule,
    SealStatus,
    BlastRadius,
    Alert,
    SensorSignal,
    HEARTBEAT_LOST_S,
    ALERTS_PER_INSTANCE_PER_MIN,
    can_transition,
)
from contracts.vultr import VultrError, VultrNotFound

from .db import (
    ActionRow,
    AlertRow,
    CaseRow,
    EvidenceRow,
    FindingRow,
    ReportRow,
    StepRow,
    SensorRow,
    WarmTwinRow,
    utcnow,
)
from .fake_twin import fake_twin_loop
from .investigator import ScriptedInvestigator
from .recorder import DbCaseRecorder
from .runner import TwinStepRunner

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


class AlertRateLimit(ValueError):
    pass


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

    def now(self) -> datetime:
        value = self.state.clock()
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    async def create_alert(self, instance_id: str, signal: SensorSignal,
                           source: str, summary: str, detail: dict[str, str],
                           *, now: datetime | None = None,
                           rate_limit: bool = True,
                           fixture_finding_ids: set[str] | None = None,
                           case_operator: str = "sensor") -> Alert:
        now = now or self.now()
        with self.state.sf() as s:
            if rate_limit:
                count = s.scalar(select(func.count()).select_from(AlertRow).where(
                    AlertRow.instance_id == instance_id,
                    AlertRow.received_at > now - timedelta(minutes=1),
                )) or 0
                if count >= ALERTS_PER_INSTANCE_PER_MIN:
                    raise AlertRateLimit(instance_id)
            live = s.execute(select(CaseRow).where(
                CaseRow.instance_id == instance_id,
                CaseRow.state.not_in([CaseState.closed.value, CaseState.failed.value]),
            ).order_by(CaseRow.created_at.desc())).scalars().first()
            number = (s.scalar(select(func.count()).select_from(AlertRow)) or 0) + 1
            row = AlertRow(id=f"alert-{number:04d}", instance_id=instance_id,
                           signal=signal.value, source=source, summary=summary,
                           detail=detail, received_at=now,
                           case_id=live.id if live else None)
            s.add(row)
            s.commit()
            result = row.to_model()
        if live is None:
            case = await self.open_case(instance_id, f"Sensor: {summary}",
                                        operator=case_operator)
            with self.state.sf() as s:
                case_row = s.get(CaseRow, case.id)
                case_row.alert_id = result.id
                alert_row = s.get(AlertRow, result.id)
                alert_row.case_id = case.id
                s.commit()
                result = alert_row.to_model()
            await self.run_case(case.id, force_full=True, auto_close=False,
                                propose_actions=fixture_finding_ids is not None,
                                fixture_finding_ids=fixture_finding_ids)
        return result

    async def check_heartbeat_losses(self) -> list[Alert]:
        """Raise at most one control-plane alert for each continuous lapse."""
        now = self.now()
        cutoff = now - timedelta(seconds=HEARTBEAT_LOST_S)
        with self.state.sf() as s:
            sensors = list(s.execute(select(SensorRow).where(
                SensorRow.is_demo.is_(False),
                func.coalesce(SensorRow.last_seen, SensorRow.enrolled_at) < cutoff
            )).scalars())
            due = []
            for sensor in sensors:
                since = sensor.last_seen or sensor.enrolled_at
                exists = s.scalar(select(func.count()).select_from(AlertRow).where(
                    AlertRow.instance_id == sensor.instance_id,
                    AlertRow.signal == SensorSignal.heartbeat_lost.value,
                    AlertRow.received_at >= since,
                ))
                if not exists:
                    due.append(sensor.instance_id)
        alerts = []
        for instance_id in due:
            alerts.append(await self.create_alert(
                instance_id, SensorSignal.heartbeat_lost, "control_plane",
                "Sensor heartbeat lost", {"threshold_s": str(HEARTBEAT_LOST_S)},
                now=now, rate_limit=False))
        return alerts

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

    async def run_case(self, case_id: str, *, force_full: bool = False,
                       auto_apply: bool = False, auto_close: bool = True,
                       propose_actions: bool = True,
                       fixture_finding_ids: set[str] | None = None) -> Case:
        """Walk the case as far as the phases implemented so far allow."""
        row = self.row(case_id)
        try:
            if not await self._adopt_warm_twin(row):
                await self._snapshot_phase(row)
                await self._twin_phase(row)
            if self.settings.full_pipeline or force_full:
                await self._investigation_phase(self.row(case_id), propose_actions,
                                                fixture_finding_ids)
                if auto_apply:
                    actions = await self.build_action_menu(case_id)
                    for action in actions:
                        await self.approve_action(case_id, action.id, "dev-demo")
                        await self.apply_action(case_id, action.id)
                    row = self.row(case_id)
                    self._move(row, CaseState.contained,
                               "development demo containment applied",
                               actor=Actor.human)
                if self.state.is_fake and auto_close:
                    await self.close_case(case_id)
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

    async def _adopt_warm_twin(self, row: CaseRow) -> bool:
        with self.state.sf() as s:
            warm = s.execute(
                select(WarmTwinRow)
                .where(WarmTwinRow.instance_id == row.instance_id,
                       WarmTwinRow.adopted_at.is_(None))
                .order_by(WarmTwinRow.created_at)
                .with_for_update()
            ).scalars().first()
            if warm is None:
                return False
            warm.adopted_at = utcnow()
            values = {
                "snapshot_id": warm.snapshot_id,
                "twin_instance_id": warm.twin_instance_id,
                "vpc_id": warm.vpc_id,
                "firewall_group_id": warm.firewall_group_id,
                "twin_internal_ip": warm.twin_internal_ip,
                "vpc_subnet": warm.vpc_subnet,
                "vpc_mask": warm.vpc_mask,
            }
            s.commit()

        self._move(row, CaseState.snapshotting, "adopting prebuilt warm snapshot")
        for name, value in values.items():
            setattr(row, name, value)
        self._touch(row)
        self.log.append(row.id, "snapshot_created", {
            "snapshot_id": row.snapshot_id,
            "instance_id": row.instance_id,
            "warm": True,
        })
        self._move(row, CaseState.restoring, "adopting pre-restored warm twin")
        token = "twreg-" + secrets.token_urlsafe(24)
        row.reg_token = token
        self._touch(row)
        self.channel.prepare_registration(row.id, token)
        twin = await self.vultr.get_instance(row.twin_instance_id)
        self.log.append(row.id, "twin_created", {
            "twin_instance_id": row.twin_instance_id,
            "vpc_id": row.vpc_id,
            "firewall_group_id": row.firewall_group_id,
            "iso_id": self.settings.iso_id,
            "warm": True,
        })
        if self.state.is_fake and self.settings.spawn_fake_twin:
            self.state.fake_twin_tasks[row.id] = asyncio.create_task(
                fake_twin_loop(self.state, row.id, token, twin.internal_ip)
            )
        try:
            ok, reason = await asyncio.wait_for(
                self.channel.wait_registered(row.id),
                timeout=self.settings.register_timeout_s,
            )
        except (TimeoutError, asyncio.TimeoutError):
            raise CaseFailure(f"warm twin {row.twin_instance_id} did not register in time")
        if not ok:
            raise CaseFailure(f"warm twin did not seal: {reason}")
        row = self.row(row.id)
        seal = SealStatus.model_validate(row.seal)
        for check, passed in (("disk_read_only", seal.disk_read_only),
                              ("egress_blocked", seal.egress_blocked)):
            self.log.append(row.id, "seal_check", SealCheck(
                case_id=row.id, check=check, passed=passed,
                output=seal.detail.get(check, "")))
        self._move(row, CaseState.sealed, "warm twin adopted and sealed")
        return True

    def detail(self, case_id: str) -> CaseDetail:
        row = self.row(case_id)
        with self.state.sf() as s:
            steps = s.execute(select(StepRow).where(StepRow.case_id == case_id)
                              .order_by(StepRow.seq)).scalars().all()
            evidence = s.execute(select(EvidenceRow).where(EvidenceRow.case_id == case_id)
                                 .order_by(EvidenceRow.id)).scalars().all()
            findings = s.execute(select(FindingRow).where(FindingRow.case_id == case_id)
                                 .order_by(FindingRow.id)).scalars().all()
            actions = s.execute(select(ActionRow).where(ActionRow.case_id == case_id)
                                .order_by(ActionRow.id)).scalars().all()
        return CaseDetail(
            case=row.to_model(), steps=[x.to_model() for x in steps],
            evidence=[x.to_model() for x in evidence],
            findings=[x.to_model() for x in findings],
            actions=[x.to_model() for x in actions],
            seal=SealStatus.model_validate(row.seal) if row.seal else None,
            blast_radius=BlastRadius.model_validate(row.blast_radius)
            if row.blast_radius else None,
        )

    def evidence_bundle(self, case_id: str) -> bytes:
        row = self.row(case_id)
        if not row.snapshot_id:
            raise ValueError("case has no snapshot")
        with self.state.sf() as s:
            evidence = s.execute(
                select(EvidenceRow).where(EvidenceRow.case_id == case_id)
                .order_by(EvidenceRow.id)
            ).scalars().all()
            report = s.get(ReportRow, case_id)
        if report is None:
            raise ValueError("case has no report")
        entries = [entry.model_dump(mode="json") for entry in self.log.entries(case_id)]
        hashes = [
            {"id": item.id, "path": item.path, "sha256": item.sha256}
            for item in evidence
        ]
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
            bundle.writestr("snapshot_id.txt", row.snapshot_id + "\n")
            bundle.writestr("file_hashes.json", json.dumps(hashes, indent=2))
            bundle.writestr("case_log.json", json.dumps(entries, indent=2))
            bundle.writestr(
                "report.json",
                report.to_model().model_dump_json(indent=2),
            )
        return output.getvalue()

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
            id="ev-001" if row.operator == "dev-demo"
            else self._next_id(EvidenceRow, row.id, "ev"),
            case_id=row.id, step_id=None,
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

    async def _investigation_phase(self, row: CaseRow,
                                   propose_actions: bool = True,
                                   fixture_finding_ids: set[str] | None = None) -> None:
        self._move(row, CaseState.investigating, "sealed investigation started")
        fixture_ids = row.operator == "dev-demo"
        if row.operator == "dev-infect":
            with self.state.sf() as s:
                fixture_ids = not bool(s.scalar(
                    select(func.count()).select_from(StepRow)
                    .where(StepRow.id.like("step-%"))))
        report = await ScriptedInvestigator(
            fixture_ids=fixture_ids,
            finding_ids=fixture_finding_ids,
        ).investigate(
            row.to_model(),
            TwinStepRunner(self.channel, self.settings),
            DbCaseRecorder(self.state.sf, self.log),
        )
        with self.state.sf() as s:
            s.add(ReportRow(
                case_id=row.id, summary=report.summary,
                timeline=[x.model_dump(mode="json") for x in report.timeline],
                ranked_actions=[x.value for x in report.ranked_actions],
                rogue_ssh_keys=report.rogue_ssh_keys,
                secrets_found=report.secrets_found,
            ))
            s.commit()
        row = self.row(row.id)
        self._move(row, CaseState.reported, report.summary, actor=Actor.agent)
        if propose_actions:
            await self.build_action_menu(row.id)

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
        token = "twreg-" + secrets.token_urlsafe(24)
        vpc_subnet = f"{vpc.v4_subnet}/{vpc.v4_subnet_mask}"
        vpc_ip = str(ipaddress.ip_network(vpc_subnet, strict=False).network_address + 3)
        user_data = base64.b64encode(json.dumps({
            "case_id": row.id, "token": token,
            "control_plane": self.settings.control_url,
            "vpc_subnet": vpc_subnet,
            "vpc_ip": vpc_ip,
        }, separators=(",", ":")).encode()).decode()
        req = CreateTwinRequest(
            region=source.region, plan=self.settings.twin_plan, label=f"bd-twin-{row.id}",
            snapshot_id=row.snapshot_id, iso_id=self.settings.iso_id,
            user_data=user_data, attach_vpc=[vpc.id], firewall_group_id=fw.id)
        fallback = self.settings.t1_fallback
        if fallback:
            twin = await self.vultr.create_instance(
                req.model_copy(update={"snapshot_id": None}))
        else:
            try:
                twin = await self.vultr.create_instance(req)
            except VultrError as e:
                if e.status_code != 400:
                    raise
                fallback = True
                twin = await self.vultr.create_instance(
                    req.model_copy(update={"snapshot_id": None}))
        # persist the twin id before anything else can fail on it: teardown
        # (F11) must always know the live instance (security review)
        row.twin_instance_id = twin.id
        self._touch(row)
        if fallback:
            # attach right after create, before any boot polling. On real
            # Vultr the instance may already be booting in this window — see
            # the day-one T1 decision (halt/attach/boot needs a contracts call).
            await self.vultr.restore_snapshot(twin.id, row.snapshot_id)
        self.log.append(row.id, "twin_created", {
            "twin_instance_id": twin.id, "vpc_id": vpc.id, "firewall_group_id": fw.id,
            "iso_id": self.settings.iso_id, "iso_attached_in_create": True,
            "snapshot_restored_after_create": fallback})
        # F4: one-time registration token, consumed at first register. FakeVultr
        # mode hands it to the in-process twin stand-in; real mode delivers it
        # to the ISO (delivery mechanism is the orchestrator's day-one call).
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
            desired.append(ActionKind.quarantine_firewall)
            if report is not None and report.rogue_ssh_keys:
                desired.append(ActionKind.revoke_ssh_key)
            desired.append(ActionKind.stop_instance)
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
        action = await self._build_action(row, kind, report=report)
        with self.state.sf() as s:
            s.add(ActionRow(**action.model_dump()))
            s.commit()
        self.log.append(row.id, "action_proposed", ActionProposed(action=action),
                        actor=Actor.agent)

    async def _build_action(self, row: CaseRow, kind: ActionKind,
                            report: ReportRow | None = None,
                            description: str | None = None,
                            created_by: Actor = Actor.agent) -> Action:
        """Build every action's trusted API fields in one backend-only place."""
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
                id=self._action_id(row, kind), case_id=row.id, kind=kind,
                target=target, api_method="PATCH", api_path=f"/v2/instances/{target}",
                api_body={"firewall_group_id": row.quarantine_group_id},
                description=description or
                            f"Move {row.instance_label} into the quarantine "
                            f"group (admin SSH only)",
                recommended=created_by is Actor.agent, created_by=created_by)
        elif kind is ActionKind.stop_instance:
            action = Action(
                id=self._action_id(row, kind), case_id=row.id, kind=kind,
                target=target, api_method="POST",
                api_path=f"/v2/instances/{target}/halt",
                description=description or f"Halt {row.instance_label}",
                created_by=created_by)
        elif kind is ActionKind.revoke_ssh_key:
            keys = "; ".join(report.rogue_ssh_keys) if report else "specified keys"
            action = Action(
                id=self._action_id(row, kind), case_id=row.id, kind=kind,
                target=target, api_method=None, api_path=None,
                description=description or
                            f"On {row.instance_label}, remove the rogue "
                            f"authorized_keys lines: {keys}", created_by=created_by)
        elif kind is ActionKind.rotate_secrets:
            paths = ", ".join(report.secrets_found) if report else "specified secrets"
            action = Action(
                id=self._action_id(row, kind), case_id=row.id, kind=kind,
                target=target, api_method=None, api_path=None,
                description=description or
                            f"Rotate the secrets found on the disk: {paths}",
                created_by=created_by)
        else:  # manual_plan: human-authored record, never executable
            action = Action(
                id=self._action_id(row, kind), case_id=row.id, kind=kind,
                target=target, api_method=None, api_path=None, api_body=None,
                description=description or "Manual remediation plan",
                created_by=created_by)
        return action

    async def add_custom_action(self, case_id: str,
                                request: CustomActionRequest) -> Action:
        row = self.row(case_id)
        if CaseState(row.state) is not CaseState.reported:
            raise TransitionError(CaseState(row.state), CaseState.reported)
        with self.state.sf() as s:
            report = s.get(ReportRow, case_id)
        action = await self._build_action(
            row, request.kind, report=report, description=request.description,
            created_by=Actor.human)
        with self.state.sf() as s:
            s.add(ActionRow(**action.model_dump()))
            s.commit()
        self.log.append(case_id, "action_proposed", ActionProposed(action=action),
                        actor=Actor.human)
        return action

    def _next_id(self, row_class, case_id: str, prefix: str) -> str:
        with self.state.sf() as s:
            n = s.scalar(select(func.count()).where(row_class.case_id == case_id)) or 0
        return f"{case_id}-{prefix}-{n + 1:03d}"

    def _action_id(self, row: CaseRow, kind: ActionKind) -> str:
        if row.operator == "dev-infect":
            candidate = {
                ActionKind.quarantine_firewall: "act-1",
                ActionKind.revoke_ssh_key: "act-2",
                ActionKind.stop_instance: "act-3",
                ActionKind.rotate_secrets: "act-4",
                ActionKind.manual_plan: "act-5",
            }[kind]
            with self.state.sf() as s:
                if s.get(ActionRow, candidate) is None:
                    return candidate
            return f"{row.id}-{candidate}"
        if row.operator == "dev-demo":
            with self.state.sf() as s:
                n = s.scalar(select(func.count()).where(ActionRow.case_id == row.id)) or 0
            return f"act-{n + 1}"
        return self._next_id(ActionRow, row.id, "act")

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
            await self._teardown(row)
        finally:
            row = self.row(case_id)
            if can_transition(CaseState(row.state), CaseState.failed):
                self._move(row, CaseState.failed, reason)
            self.channel.cleanup_case(case_id)

    # ------------------------------------------------------------- F11: teardown
    async def close_case(self, case_id: str) -> Case:
        row = self.row(case_id)
        state = CaseState(row.state)
        if state not in (CaseState.reported, CaseState.contained):
            raise TransitionError(state, CaseState.closed)
        try:
            await self._teardown(row)
        finally:
            self.channel.cleanup_case(case_id)
        row = self.row(case_id)
        row.closed_at = utcnow()
        self._touch(row)
        self._move(row, CaseState.closed, "twin destroyed, evidence sealed")
        return self.model(case_id)

    async def _teardown(self, row: CaseRow) -> None:
        """Best-effort deletion in dependency order.

        Every resource gets a deletion attempt even if an earlier call fails. A live
        twin is the security-critical failure, so surface that error after recording
        all results; fail_case's finally block can still make the case terminal.
        """
        errors: list[Exception] = []
        twin_status = 404 if not row.twin_instance_id else 0
        vpc_deleted = row.vpc_id is None

        if row.twin_instance_id:
            try:
                await self.vultr.delete_instance(row.twin_instance_id)
            except VultrNotFound:
                pass
            except Exception as e:
                errors.append(e)
            try:
                await self.vultr.get_instance(row.twin_instance_id)
                twin_status = 200
            except VultrNotFound:
                twin_status = 404
            except Exception as e:
                errors.append(e)

        if row.vpc_id:
            try:
                await self.vultr.delete_vpc(row.vpc_id)
                vpc_deleted = True
            except VultrNotFound:
                vpc_deleted = True
            except Exception as e:
                errors.append(e)

        if row.firewall_group_id:
            try:
                await self.vultr.delete_firewall_group(row.firewall_group_id)
            except VultrNotFound:
                pass
            except Exception as e:
                errors.append(e)

        blast_radius = self.blast_radius(row.id)
        row.blast_radius = blast_radius.model_dump(mode="json")
        self._touch(row)
        payload = {
            "twin_instance_id": row.twin_instance_id,
            "twin_status_code": twin_status,
            "vpc_id": row.vpc_id,
            "vpc_deleted": vpc_deleted,
            "firewall_group_id": row.firewall_group_id,
            "errors": [f"{type(e).__name__}: {e}" for e in errors],
        }
        self.log.append(row.id, "teardown", payload)
        if row.twin_instance_id:
            self.log.append(row.id, "teardown_done", TeardownDone(
                case_id=row.id,
                twin_instance_id=row.twin_instance_id,
                twin_status_code=twin_status,
                vpc_deleted=vpc_deleted,
                blast_radius=blast_radius,
            ))
        if twin_status != 404:
            raise CaseFailure(f"twin {row.twin_instance_id} still exists after teardown")
        if errors:
            raise CaseFailure("teardown incomplete: " + "; ".join(str(e) for e in errors))

    def blast_radius(self, case_id: str) -> BlastRadius:
        row = self.row(case_id)
        packets_out = 0
        containers_left = 0
        for job in self.channel.jobs_with_results(case_id):
            result = job.to_result()
            if result is not None:
                packets_out += result.packets_out
                containers_left += result.containers_left

        writes = 0
        approved = False
        production_path = f"/v2/instances/{row.instance_id}"
        for entry in self.log.entries(case_id):
            if entry.event == "action_approved":
                approved = True
            if approved:
                continue
            if entry.event == "production_write":
                writes += 1
            elif entry.event == "api_call":
                method = str(entry.payload.get("method", "")).upper()
                path = str(entry.payload.get("path", ""))
                if method in {"POST", "PATCH", "PUT", "DELETE"} and path.startswith(
                    production_path
                ):
                    writes += 1
            elif entry.event == "action_applied":
                action = entry.payload.get("action", {})
                if action.get("target") == row.instance_id:
                    writes += 1
        return BlastRadius(
            prod_writes_before_approval=writes,
            packets_out=packets_out,
            containers_left=containers_left,
        )
