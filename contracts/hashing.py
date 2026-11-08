"""Hash-chain rule for the case log (F12). One definition, used by the backend
when appending and by anyone verifying a bundle."""
from __future__ import annotations

import hashlib
import json

from .models import GENESIS_HASH, LogEntry


def canonical(entry: LogEntry) -> bytes:
    body = entry.model_dump(mode="json", exclude={"hash"})
    return json.dumps(body, sort_keys=True, separators=(",", ":")).encode()


def entry_hash(entry: LogEntry) -> str:
    """sha256 over canonical JSON of every field except `hash` (prev_hash included)."""
    return hashlib.sha256(canonical(entry)).hexdigest()


def verify_chain(entries: list[LogEntry]) -> int | None:
    """Return the seq of the first bad entry, or None if the chain is intact."""
    prev = GENESIS_HASH
    for e in sorted(entries, key=lambda e: e.seq):
        if e.prev_hash != prev or e.hash != entry_hash(e):
            return e.seq
        prev = e.hash
    return None
