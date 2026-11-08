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
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from contracts.events import StateChanged
from contracts.models import (
    Actor,
    Case,
    CaseState,
    CreateTwinRequest,
    Evidence,
    can_transition,
)
from contracts.vultr import VultrError, VultrNotFound

from .db import CaseRow, EvidenceRow, utcnow

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
            id=self._next_evidence_id(row.id), case_id=row.id, step_id=None,
            path=f"snapshot:{snap.id}", sha256=hashlib.sha256(snap.id.encode()).hexdigest(),
            excerpt=f"Vultr snapshot {snap.id} of {row.instance_id} at "
                    f"{utcnow().isoformat()}Z",
        ))

    def _next_evidence_id(self, case_id: str) -> str:
        with self.state.sf() as s:
            n = s.scalar(select(func.count()).where(EvidenceRow.case_id == case_id)) or 0
        return f"{case_id}-ev-{n + 1:03d}"

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
        twin = await self.vultr.create_instance(CreateTwinRequest(
            region=source.region, plan=self.settings.twin_plan, label=f"bd-twin-{row.id}",
            snapshot_id=row.snapshot_id,
            iso_id=None if self.settings.t1_fallback else self.settings.iso_id,
            attach_vpc=[vpc.id], firewall_group_id=fw.id))
        if self.settings.t1_fallback:
            # attach before the first boot poll, so the cloned OS never boots
            await self.vultr.attach_iso(twin.id, self.settings.iso_id)
        row.twin_instance_id = twin.id
        self._touch(row)
        self.log.append(row.id, "twin_created", {
            "twin_instance_id": twin.id, "vpc_id": vpc.id, "firewall_group_id": fw.id,
            "iso_id": self.settings.iso_id, "t1_fallback": self.settings.t1_fallback})
        deadline = utcnow() + timedelta(seconds=self.settings.boot_timeout_s)
        while True:
            twin = await self.vultr.get_instance(twin.id)
            if twin.status == "active":
                break
            if utcnow() > deadline:
                raise CaseFailure(f"twin {twin.id} did not boot in time")
            await asyncio.sleep(self.settings.poll_interval_s)

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
