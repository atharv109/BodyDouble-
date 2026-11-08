"""The twin channel (F4): registration, heartbeat, and the job pull loop.

The forensics ISO never accepts inbound connections — it checks in over the
VPC with a one-time token, then long-polls for ToolCalls and posts ToolResults
over the same session. Every /twin/* call must come from the case's VPC subnet
and carry a valid X-Twin-Session.
"""
from __future__ import annotations

import asyncio
import ipaddress
import secrets
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from contracts.models import SealStatus, ToolCall, ToolResult, TwinRegisterResponse

from .db import CaseRow, JobRow, utcnow


class TwinChannelError(Exception):
    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code
        self.detail = detail


class TwinSession:
    __slots__ = ("key", "case_id", "vpc_ip", "last_seen")

    def __init__(self, key: str, case_id: str, vpc_ip: str):
        self.key = key
        self.case_id = case_id
        self.vpc_ip = vpc_ip
        self.last_seen = utcnow()


def in_subnet(ip: str, subnet: str | None, mask: int | None) -> bool:
    try:
        addr = ipaddress.ip_address(ip)
        net = ipaddress.ip_network(f"{subnet}/{mask}", strict=False)
    except ValueError:
        return False
    return addr in net


class TwinChannel:
    """All in-process state for the live twin channel of one app instance."""

    def __init__(self, session_factory, settings):
        self._sf = session_factory
        self._settings = settings
        self.sessions: dict[str, TwinSession] = {}
        self._queues: dict[str, asyncio.Queue[str]] = {}      # case_id -> queued job ids
        self._pending: dict[str, asyncio.Future[ToolResult]] = {}  # job_id -> future
        self._registered: dict[str, tuple[asyncio.Event, bool, str]] = {}  # case_id -> (ev, ok, reason)

    # ------------------------------------------------------------- register
    def prepare_registration(self, case_id: str, token: str) -> None:
        """Called by the service right before the twin boots (token handed to
        the ISO via instance user_data in real mode)."""
        ev = asyncio.Event()
        self._registered[case_id] = (ev, True, "")

    async def wait_registered(self, case_id: str) -> tuple[bool, str]:
        ev, _, _ = self._registered[case_id]
        await ev.wait()
        _, ok, reason = self._registered[case_id]
        return ok, reason

    def notify_seal_failed(self, case_id: str, reason: str) -> None:
        if case_id in self._registered:
            ev = self._registered[case_id][0]
            self._registered[case_id] = (ev, False, reason)
            ev.set()

    def cleanup_case(self, case_id: str) -> None:
        self._registered.pop(case_id, None)
        self._queues.pop(case_id, None)
        self.sessions = {k: v for k, v in self.sessions.items() if v.case_id != case_id}
        for job_id, (owner, fut) in list(self._pending.items()):
            if owner == case_id and not fut.done():
                fut.cancel()
            if owner == case_id:
                self._pending.pop(job_id, None)

    def register(self, case_id: str, token: str, vpc_ip: str, seal: SealStatus,
                 client_ip: str, case_row=None) -> TwinRegisterResponse:
        # atomic one-time consume: token check AND null-out in one DB transaction
        with self._sf() as s:
            row = s.get(CaseRow, case_id)
            if row is None:
                raise TwinChannelError(404, "unknown case")
            if row.reg_token is None or not secrets.compare_digest(row.reg_token, token):
                raise TwinChannelError(403, "unknown or already-used registration token")
            if not in_subnet(client_ip, row.vpc_subnet, row.vpc_mask):
                raise TwinChannelError(403, f"registration not from the case VPC (source {client_ip})")
            if vpc_ip != client_ip:
                raise TwinChannelError(403, f"claimed vpc_ip {vpc_ip} != source {client_ip}")
            if row.twin_internal_ip is not None and vpc_ip != row.twin_internal_ip:
                raise TwinChannelError(
                    403, f"registration source {vpc_ip} is not the case's assigned VPC IP"
                )
            row.reg_token = None  # one-time: consumed
            row.twin_internal_ip = vpc_ip
            row.seal = seal.model_dump(mode="json")
            s.commit()
            subnet, mask = row.vpc_subnet, row.vpc_mask
        key = "twinsess-" + secrets.token_urlsafe(24)
        self.sessions[key] = TwinSession(key, case_id, vpc_ip)
        if case_id in self._registered:
            # the service may already have stopped waiting (case failed, or a
            # real ISO registering late); set the event only if it still cares
            ev, _, _ = self._registered[case_id]
            self._registered[case_id] = (ev, seal.sealed, "" if seal.sealed else "seal checks failed")
            ev.set()
        return TwinRegisterResponse(session_key=key)

    # ------------------------------------------------------------- session
    def require_session(self, session_key: str | None, client_ip: str, case_row) -> TwinSession:
        sess = self.sessions.get(session_key or "")
        if sess is None or sess.case_id != case_row.id:
            raise TwinChannelError(401, "missing or unknown X-Twin-Session")
        if (utcnow() - sess.last_seen) > timedelta(seconds=self._settings.heartbeat_ttl_s):
            raise TwinChannelError(401, "twin session expired")
        if not in_subnet(client_ip, case_row.vpc_subnet, case_row.vpc_mask):
            raise TwinChannelError(403, f"call not from the case VPC (source {client_ip})")
        if client_ip != sess.vpc_ip:
            raise TwinChannelError(403, "twin session is bound to a different VPC IP")
        return sess

    def resolve_session(self, session_key: str | None, client_ip: str) -> tuple[TwinSession, CaseRow]:
        """Session + case row for the /twin/* routes that carry no case id
        (heartbeat, jobs): key lookup, then the full require_session checks."""
        sess = self.sessions.get(session_key or "")
        if sess is None:
            raise TwinChannelError(401, "missing or unknown X-Twin-Session")
        with self._sf() as s:
            row = s.get(CaseRow, sess.case_id)
        if row is None:
            raise TwinChannelError(404, "unknown case")
        self.require_session(session_key, client_ip, row)
        return sess, row

    def heartbeat(self, sess: TwinSession) -> None:
        sess.last_seen = utcnow()

    # ------------------------------------------------------------- jobs
    def enqueue(self, call: ToolCall) -> asyncio.Future[ToolResult]:
        """Queue a job for the twin and return the future its result resolves."""
        with self._sf() as s:
            s.add(JobRow(id=call.job_id, case_id=call.case_id, tool=call.tool.value,
                         args=call.args, enqueued_at=utcnow()))
            s.commit()
        self._queues.setdefault(call.case_id, asyncio.Queue()).put_nowait(call.job_id)
        fut: asyncio.Future[ToolResult] = asyncio.get_running_loop().create_future()
        self._pending[call.job_id] = (call.case_id, fut)
        return fut

    async def next_job(self, sess: TwinSession, case_row, timeout_s: float) -> ToolCall | None:
        """Long-poll one queued job; None on timeout. 410 once the case is over."""
        if case_row.state in ("closed", "failed"):
            raise TwinChannelError(410, "case is closed")
        q = self._queues.get(sess.case_id)
        if q is None:
            await asyncio.sleep(0)
            return None
        try:
            job_id = await asyncio.wait_for(q.get(), timeout_s)
        except (TimeoutError, asyncio.TimeoutError):
            return None
        with self._sf() as s:
            row = s.get(JobRow, job_id)
            return ToolCall(job_id=row.id, case_id=row.case_id, tool=row.tool, args=row.args or {})

    def submit_result(self, sess: TwinSession, job_id: str, result: ToolResult) -> None:
        with self._sf() as s:
            row = s.get(JobRow, job_id)
            if row is None or row.case_id != sess.case_id:
                raise TwinChannelError(404, "job not found for this case")
            if row.result is not None:
                raise TwinChannelError(409, "job already has a result")
            row.result = result.model_dump(mode="json")
            s.commit()
        entry = self._pending.pop(job_id, None)
        fut = entry[1] if entry else None
        if fut and not fut.done():
            fut.set_result(result)

    def jobs_with_results(self, case_id: str) -> list[JobRow]:
        with self._sf() as s:
            return list(s.execute(select(JobRow).where(JobRow.case_id == case_id)).scalars())
