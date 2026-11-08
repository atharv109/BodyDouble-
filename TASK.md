# Worker: backend

You own: backend/ only. Never edit anything outside it. Never edit contracts/.
Ignore Claude.md in this folder: it is the orchestrator's file, not yours. This TASK.md is your spec;
the PRD (PRD.md in the repo root, plain text; NEVER open the PDF, it costs ~450k tokens) is the reference behind it.

## Before every item
- Read your inbox ~/bd-bridge/to-backend.md and act on anything new first.

## Setup (do once, before F1; commit as "backend: setup")
- Create backend/pyproject.toml (FastAPI, uvicorn, SQLAlchemy, sse-starlette or plain StreamingResponse,
  pytest, pytest-asyncio) with the repo root as an editable path dependency so `import contracts` works.
  Do not touch the root pyproject.toml.
- Postgres via SQLAlchemy (DATABASE_URL); tests may use SQLite through the same models.
- Vultr access only through contracts.vultr.VultrClient. Default and tests: FakeVultr. RealVultr only
  when VULTR_API_KEY is set; you never set it.
- Keep the live API up the whole time on :8000:
  `hc run --bg --name api --cwd C:/dev/wt-backend uv run --project backend uvicorn backend.app:app --reload --port 8000`
- Until forensics/ is merged, use a scripted stub `Investigator` (contracts.agent) inside backend/.

## Checklist
- [x] F1: GET /instances lists the account's instances; POST /cases opens a case on one. Done when: case row created with instance ID, reason, timestamp. Test file: backend/tests/test_f01_open_case.py
- [x] F2: snapshot the suspect instance through VultrClient and poll until complete. Done when: snapshot ID stored; status `complete`. Test file: backend/tests/test_f02_snapshot.py
- [x] F3: create the twin from the snapshot on a dedicated VPC with an inbound-deny firewall group, booting the forensics ISO (snapshot_id + iso_id in one create call; the T1 fallback FakeVultr supports is fine behind a flag). Done when: twin instance ID stored; ISO attached before the cloned OS boots. Test file: backend/tests/test_f03_twin.py
- [x] F4: POST /twin/register (one-time token, VPC source address only), POST /twin/heartbeat, GET /twin/jobs/next, POST /twin/jobs/{id}/result, all with X-Twin-Session; plus the StepRunner and CaseRecorder from contracts/agent.py. Done when: heartbeat received from the VPC address; a request from a non-VPC address or a reused token is rejected. Test file: backend/tests/test_f04_twin_channel.py
- [x] F9: containment action menu built by code from findings (contracts ActionKind menu, exact Vultr API call on each); POST /cases/{id}/actions/{action_id}/approve requires a human session. Done when: nothing is applied without an Approve call. Test file: backend/tests/test_f09_actions.py
- [x] F10: apply approved actions to production via VultrClient. Done when: API responses logged in the case log; the production firewall group is visibly changed (FakeVultr state). Test file: backend/tests/test_f10_apply.py
- [ ] F11: POST /cases/{id}/close tears down the twin and its VPC (also on `failed`, in try/finally). Done when: instance gone (API 404) and that is recorded in the case log. Test file: backend/tests/test_f11_teardown.py
- [ ] F12: hash-chained case log using contracts.hashing. Done when: each entry includes the previous entry's hash; tampering is detected. Test file: backend/tests/test_f12_log.py
- [ ] Also: GET /cases/{id} and GET /cases/{id}/stream (SSE, contracts.events) for the full state machine. Done when: one POST /cases on FakeVultr walks opened -> closed unattended and every event is valid per contracts.events. Test file: backend/tests/test_e2e_fakevultr.py
- [ ] POST /dev/fake-case: runs a full case on FakeVultr with the stub Investigator so web/ can build against live SSE. Done when: its stream parses with contracts.events.parse_sse and covers every event name in contracts/fixtures/fake_case.sse. Test file: backend/tests/test_dev_fake_case.py

- [ ] F14: GET /cases/{id}/bundle exports the evidence bundle as a zip: snapshot ID, file hashes, case log, report. Done when: the zip from a FakeVultr run contains all four and its case log passes contracts.hashing.verify_chain. Test file: backend/tests/test_f14_bundle.py
- [ ] F16: blast-radius summary (contracts models): writes to production before approval, packets out, containers left running, computed from the case log and twin results. Done when: a FakeVultr run reports 0 / 0 / 0, and an injected pre-approval write makes it non-zero. Test file: backend/tests/test_f16_blast_radius.py
- [ ] F17: warm twin: `uv run --project backend python -m backend.warm_twin INSTANCE_ID` pre-snapshots and pre-restores a twin; the next POST /cases on that instance adopts it and skips snapshot/restore (still emitting the same events). Done when: on FakeVultr a case on a warmed instance reaches `sealed` without a new snapshot or create call. Test file: backend/tests/test_f17_warm_twin.py

## Talking to other workers
- Need something from another worker: append a request to ~/bd-bridge/to-OTHER.md and keep
  working on something else.
- You own endpoint shapes and may change them in code, but log every change in ~/bd-bridge/to-frontend.md.
- Need a contracts/ change or a decision: run `hc send t1 "QUESTION from backend: ..."` and stop.
- When every box is ticked: run `hc send t1 "DONE: backend"`.

## Rules
- Commit after each item with the F-number in the message.
- Tick the box only after its test passes.
- Never git push, never git reset --hard, never touch the main branch.
- Never use a real Vultr API key or real inference key.
