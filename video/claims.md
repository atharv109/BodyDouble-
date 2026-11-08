# Body Double — technical claims ledger

Every spoken or on-screen claim in the film, with the repository source it
derives from. Anything not in this list does not go in the film.

| # | Film claim | Where it is true in the codebase |
| - | --- | --- |
| 1 | "shop-prod is running hot … nobody does incident response" | The demo victim is `shop-prod` with the reason "CPU at 100% overnight, unknown process." — `contracts/fixtures/fake_case_detail.json` (`case.reason`), planted indicators in `demo/plant.sh`, `PRD.md` ("The primary user … gets the 2 a.m. alert") |
| 2 | Opening a case never touches production; investigation runs on a copy | `backend/backend/service.py` `run_case` — case flow snapshots then restores to a new twin; `README.md` ("Production continues serving traffic; containment changes happen only after a human reviews and approves") |
| 3 | A Vultr snapshot is taken and becomes evidence item #1 | F2 (`PRD.md`); `backend/backend/service.py` snapshot + poll loop; snapshot id `snap-0001` appears in case fixture with state detail "snapshot … complete" |
| 4 | The twin boots the forensics ISO, never the cloned OS | `contracts/vultr.py` create call supplies `iso_id` + `snapshot_id`; `README.md` ("The twin boots the Body Double forensics ISO with the copied disk mounted read-only"); PRD T1 |
| 5 | Twin lives on a private VPC behind an inbound-deny firewall | `backend/backend/service.py` (VPC + firewall group creation), `vpc_id=vpc-0002`, `firewall_group_id=fw-0003` in fixture; `README.md` Vultr-services table |
| 6 | Cloned disk is mounted read-only | `iso/rootfs/etc/bd/boot.sh:43` — `mount -o ro,noexec,nosuid,nodev`; shown on screen by the `disk_read_only` seal check (`contracts/events.py` `SealCheck`) |
| 7 | Outbound traffic is dropped | `iso/rootfs/etc/bd/egress.nft` — default-DROP, "Vultr Firewall filters only inbound traffic, so the ISO itself default-DROPs"; `egress_blocked` seal check |
| 8 | "Nothing starts unless both checks pass" | Seal checks gate investigation: `backend/backend/service.py` (sealed → investigating transition), shown by rail + `seal-status` in `web/src/case/Terminal.tsx` |
| 9 | The agent writes its own triage scripts against the copy | Planner role + tool list (`os_facts`, `persistence_scan`, `auth_scan`, `binary_integrity`, `detonate`, …) — `contracts/agent.py`, `backend/backend/investigator.py`; steps carry `code`, `stdout`, `exit_code`, `duration_ms` (`contracts/models.py` Step) |
| 10 | Findings: cron backdoor, rogue SSH key, replaced `/usr/bin/top`, dropped miner | `contracts/fixtures/fake_case_detail.json` — T1053.003 cron every minute, T1098.004 unknown SSH key, T1036.005 `/usr/bin/top` replaced, T1496 miner file; planted by `demo/plant.sh` |
| 11 | Every finding cites evidence IDs | `contracts/models.py` Finding `evidence_ids[]`; validated against the case's evidence in `backend/backend/investigator.py` |
| 12 | Suspicious code detonates in a no-network container, fake DNS answers and logs the lookup | `forensics/bd_forensics/sandbox.py` (gVisor `runsc`, `--network none`, fake resolver), `iso/build.sh:121` (gVisor), `README.md` ("A fake DNS resolver records attempted lookups without letting packets leave"); `dns_captured` event (`contracts/events.py`) |
| 13 | The C2 beacon is caught, nothing leaves | `dns_captured` in fixture (query → sinkhole); sandbox meters `packets out 0`, `containers left 0` (`contracts/models.py` BlastRadius) |
| 14 | The attacker's note to the AI becomes a finding, not an instruction | `backend/backend/investigator.py` — evidence artifacts carry `injection_flag`, text addressing an AI is "treated as hostile evidence and becomes an injection finding" (`README.md`); finding "Attacker left instructions for an AI investigator" with evidence `ev-008` in fixture |
| 15 | Containment is a fixed menu proposed with the exact Vultr API call; nothing is automatic | `backend/backend/app.py:509-517` `POST /cases/{id}/actions/{action_id}/approve` (F9) requires `Depends(require_human)` — model or twin traffic cannot mint an operator session (`backend/backend/sessions.py`, `README.md`); action carries `api_method`, `api_path`, `api_body` (`contracts/models.py` Action) |
| 16 | One approval applies a quarantine firewall to production | Fixture action `quarantine_firewall · PATCH /v2/instances/inst-shop-prod`, status `applied`; `action_applied` event with API response |
| 17 | The twin and its VPC are destroyed; the twin id 404s | `contracts/events.py` `TeardownDone` (`twin_status_code` 404 expected, `vpc_deleted`); shown as "twin destroyed · GET … returned 404" in `web/src/case/Terminal.tsx` |
| 18 | Blast radius: 0 writes to production before approval, 0 packets out, 0 containers left | `contracts/fixtures/fake_case_detail.json` `blast_radius`; `web/src/routes/Close.tsx` BLAST panel; F16 in `PRD.md` |
| 19 | Snapshot, hashes and hash-chained case log export as a bundle | F14 (`PRD.md`), `GET /cases/{id}/bundle` (`contracts/endpoints.py`), hash chain in `contracts/hashing.py` + log table `prev_hash`/`hash` |
| 20 | "Built during Vultr Agent Rush · Nov 3–8 2026" | `README.md` ("Built during the event, Nov 3 to 8 2026") |

## Capture honesty notes

- Footage records the real backend in FakeVultr mode (no real Vultr key; the
  README documents that mode). Instance ids like `inst-shop-prod` and
  `snap-0001` are the fixture's identifiers and appear on screen as recorded.
- In local FakeVultr mode the investigation is a deterministic replay of the
  recorded story (`backend/backend/investigator.py` — "Deterministic replay of
  the recorded FakeVultr investigation story"); with `VULTR_INFERENCE_KEY`
  set the same pipeline calls Vultr Serverless Inference for the planner,
  analyst and reporter (`contracts/agent.py`, README "How the agent performs
  real work"). The on-screen steps, evidence and findings the film shows are
  what the product itself renders in either mode.
- For legibility, capture raises `POLL_INTERVAL_S` so state changes are
  visible instead of flashing in ~50 ms (`backend/backend/config.py:91` —
  env override exists for this). Event order, payloads and end states are
  byte-identical to the default run; only the polling cadence differs.
- The detonation "runs" on the in-process fake twin stand-in
  (`backend/backend/fake_twin.py`) in capture mode; the real execution path is
  the forensics ISO (`iso/`) and `forensics/bd_forensics/sandbox.py`. The
  on-screen evidence shown in the film is what the product itself renders.
- The UI-opened case (console footage, pass A) and the demo case
  (`POST /dev/fake-case`, pass B) both read `case-0001` on screen: the dev
  endpoint resets the database before opening its case. Pass B's approve and
  close clicks are real UI interactions against the real endpoint
  (`POST /cases/{id}/actions/{action_id}/approve` → 202).
