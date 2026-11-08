from __future__ import annotations

from contracts.hashing import verify_chain
from contracts.models import Actor, GENESIS_HASH


def test_case_log_is_hash_chained_and_tampering_is_detected(state):
    case_id = "case-chain"
    first = state.log.append(case_id, "opened", {"reason": "alert"})
    second = state.log.append(
        case_id, "evidence_added", {"path": "/etc/cron.d/backdoor"}, Actor.agent
    )
    third = state.log.append(case_id, "reported", {"findings": 1})

    entries = state.log.entries(case_id)
    assert [entry.seq for entry in entries] == [0, 1, 2]
    assert first.prev_hash == GENESIS_HASH
    assert second.prev_hash == first.hash
    assert third.prev_hash == second.hash
    assert verify_chain(entries) is None

    entries[1].payload["path"] = "/etc/cron.d/clean"
    assert verify_chain(entries) == 1
