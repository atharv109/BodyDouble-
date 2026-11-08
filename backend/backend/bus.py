"""In-process pub/sub carrying formatted SSE frames to connected streams.

The case log (log.py) publishes here whenever it appends an entry whose event
is one of contracts.events EventNames; GET /cases/{id}/stream replays the log
first and then drains its queue. Queues carry (seq, frame) so a subscriber can
drop anything the replay already covered.
"""
from __future__ import annotations

import asyncio


class CaseBus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue[tuple[int, str]]]] = {}

    def subscribe(self, case_id: str) -> asyncio.Queue[tuple[int, str]]:
        q: asyncio.Queue[tuple[int, str]] = asyncio.Queue()
        self._subs.setdefault(case_id, set()).add(q)
        return q

    def unsubscribe(self, case_id: str, q: asyncio.Queue[tuple[int, str]]) -> None:
        if subs := self._subs.get(case_id):
            subs.discard(q)
            if not subs:
                self._subs.pop(case_id, None)

    def publish(self, case_id: str, seq: int, frame: str) -> None:
        for q in self._subs.get(case_id, ()):
            q.put_nowait((seq, frame))
