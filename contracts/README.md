# contracts/ — orchestrator-owned. Workers import; never edit.

| File | What it pins |
|---|---|
| `models.py` | 6 tables (`Case`, `Step`, `Evidence`, `Finding`, `Action`, `LogEntry`), case state machine, Vultr shapes, HTTP bodies, twin job shapes |
| `endpoints.py` | Control-plane HTTP API (PRD table + twin pull channel `/twin/jobs/*`, `/twin/heartbeat`) |
| `events.py` | SSE event names, payload models, `format_sse` / `parse_sse` |
| `hashing.py` | Case-log hash-chain rule (`entry_hash`, `verify_chain`) |
| `vultr.py` | `VultrClient` Protocol, `FakeVultr`, `RealVultr` |
| `agent.py` | backend ⇄ forensics seam: `Investigator`, `StepRunner`, `CaseRecorder`, `Report`, guardrail constants |
| `fixtures/fake_case.sse` | Recorded SSE of one full fake case (shop-prod, 5 planted indicators) — replay this in `web/` |
| `fixtures/fake_case_detail.json` | `GET /cases/{id}` for that case after close |
| `schema/*.json` | JSON Schema for TS type generation in `web/` |

Folder ownership: `backend/` (F1–F4, F9–F12), `forensics/` (F5–F8, F13), `web/`, `video/`.

```
uv sync && uv run pytest contracts                  # contract tests
uv run python -m contracts.fixtures.make_fixture    # regenerate fixture (orchestrator only)
```

Need a change? Stop and end your turn with `QUESTION: ...`. The orchestrator edits, commits, merges and rebases.
