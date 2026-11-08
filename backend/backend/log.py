"""The case log (F12): append-only, hash-chained with contracts.hashing, and
the source of truth for the SSE stream.

Every entry with `event` in contracts.events.EventName is a live SSE frame:
the log IS the event stream, plus finer-grained non-broadcast entries
(api_call, evidence_added, teardown details) that make the log complete.
"""
from __future__ import annotations

from typing import Any

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from contracts.events import EventName, PAYLOADS, format_sse
from contracts.hashing import entry_hash
from contracts.models import GENESIS_HASH, Actor, LogEntry

from .db import LogEntryRow, utcnow


class CaseLog:
    def __init__(self, session_factory: sessionmaker, bus):
        self._sf = session_factory
        self._bus = bus

    # ------------------------------------------------------------- append
    def append(self, case_id: str, event: str, payload: BaseModel | dict[str, Any],
               actor: Actor = Actor.system) -> LogEntry:
        if isinstance(payload, BaseModel):
            payload = payload.model_dump(mode="json")
        with self._sf() as s:
            last = s.execute(
                select(LogEntryRow.seq, LogEntryRow.hash)
                .where(LogEntryRow.case_id == case_id)
                .order_by(LogEntryRow.seq.desc()).limit(1)
            ).first()
            seq = last.seq + 1 if last else 0
            entry = LogEntry(
                seq=seq, case_id=case_id, ts=utcnow(), actor=actor, event=event,
                payload=payload, prev_hash=last.hash if last else GENESIS_HASH,
                hash="placeholder",  # replaced by entry_hash below
            )
            entry.hash = entry_hash(entry)
            s.add(LogEntryRow(**entry.model_dump()))
            s.commit()
        if event in EventName._value2member_map_:
            name = EventName(event)
            self._bus.publish(case_id, seq, format_sse(name, seq, PAYLOADS[name].model_validate(payload)))
        return entry

    # ------------------------------------------------------------- read
    def entries(self, case_id: str) -> list[LogEntry]:
        with self._sf() as s:
            rows = s.execute(
                select(LogEntryRow).where(LogEntryRow.case_id == case_id).order_by(LogEntryRow.seq)
            ).scalars().all()
            return [r.to_model() for r in rows]

    def sse_replay(self, case_id: str) -> tuple[str, int]:
        """All broadcastable entries as one SSE text, plus the last seq sent."""
        frames: list[str] = []
        last = -1
        for e in self.entries(case_id):
            if e.event in EventName._value2member_map_:
                name = EventName(e.event)
                frames.append(format_sse(name, e.seq, PAYLOADS[name].model_validate(e.payload)))
                last = e.seq
        return "".join(frames), last

    @property
    def event_names(self) -> set[str]:
        return set(EventName._value2member_map_)

    def format_entry(self, entry: LogEntry) -> str:
        name = EventName(entry.event)
        return format_sse(name, entry.seq, PAYLOADS[name].model_validate(entry.payload))
