"""CaseService: the case state machine. One method per phase of a case; every
mutation goes through the hash-chained case log. The state machine itself is
contracts.models.CASE_TRANSITIONS — this file only walks legal transitions.

Phases are added one per checklist item (F1 open, F2 snapshot, F3 twin,
F4 register/seal, then investigate -> report -> approve -> teardown).
"""
from __future__ import annotations

from sqlalchemy import select

from contracts.events import StateChanged
from contracts.models import Actor, Case, CaseState, can_transition
from contracts.vultr import VultrNotFound

from .db import CaseRow, utcnow


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
        try:
            instance = await self.vultr.get_instance(instance_id)
        except VultrNotFound as e:
            raise LookupError(f"unknown instance {instance_id}") from e
        case_id = self.next_case_id()
        row = CaseRow(
            id=case_id, instance_id=instance_id, instance_label=instance.label,
            reason=reason, state=CaseState.opened.value, created_at=utcnow(),
            operator=operator,
        )
        with self.state.sf() as s:
            s.add(row)
            s.commit()
        self.log.append(case_id, "state_changed",
                        StateChanged(case_id=case_id, from_state=None,
                                     to_state=CaseState.opened,
                                     detail="opened by operator"),
                        actor=Actor.human)
        return row.to_model()

    async def run_case(self, case_id: str) -> Case:
        """Walk the case as far as the phases implemented so far allow."""
        row = self.row(case_id)
        try:
            # phases are added here as the checklist grows (F2, F3, F4, ...)
            pass
        except CaseFailure as e:
            await self.fail_case(case_id, str(e))
        return self.model(case_id)

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
