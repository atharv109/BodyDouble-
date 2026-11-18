# Gate 2 / real run 01: summary (backend worker)

Date: 2026-11-17 to 2026-11-18 (EST). Region `ewr`, plan `vc2-1c-1gb`, investigation
VPC `ab6a9e85` (10.1.96.0/20), forensics ISO `97962862`. Every claim below cites a
file in this folder (`evals/results/real-run-01/`). Paths are relative to it.

## How the twin is sealed (read this first)

**The ESP swap is done out-of-band by the B3 driver, not by the control plane.** While
the backend waits in `restoring` for the sealed registration, `scripts/real_run_01_b3.py`
SSHes through bd-cp into the clone's own OS (using the demo snapshot's cloud-init key)
and swaps the EFI loader so that the next boot runs the forensics ISO. This is exactly
the Gate 1 run-13 flow. **The control plane never holds an SSH key into the twin's
clone.** It holds only the Vultr and inference credentials, and it reaches the twin
only through the twin's own pull-based channel (`/twin/register`, `/twin/jobs/*`).

Consequence (W1, W3): before that swap, **the clone's own OS runs, unsealed, with its
public IPv4 and open outbound internet**, for about 39 to 61 s. The 5/5 egress-blocked
seal result applies to the **sealed ISO boot only**.

## Claims and evidence

| # | Claim | Evidence |
|---|---|---|
| W1 | Before the ESP swap the restored clone's own Ubuntu has full outbound internet from its public IPv4: HTTPS 443 and HTTP 80 answered 200 and echoed 66.135.8.66, DNS resolved, ICMP 1/1, at uptime 23-39 s. It ran unsealed for about 61 s (about 39 s in Gate 1 run 13, without probes). | `preswap-egress/probe.txt` (VERDICT), `preswap-egress/probe.rc.json`, `../real-mode/S5/real-run-02-w1/` |
| W2 | No Vultr API option removes that window. (a) A VPC-only twin needs a NAT gateway, and the NAT gateway gives it egress. (b) `power_on:false` is ignored, a firewall "out drop" rule is coerced to accept, and a halted instance powers itself on when a restore completes (+183 s). | `preswap-isolation/findings.md` (per-attempt tables with saved API responses), `preswap-isolation/w2b-d2/D2-restore-halted-timeline.txt` |
| W2 | NAT gateway endpoints: `POST/GET /v2/vpcs/{vpc}/nat-gateway`, `DELETE /v2/vpcs/{vpc}/nat-gateway/{id}` (204, or 422 while VPC-only instances exist). The flat `/v2/nat-gateways` path returns 404. | `preswap-isolation/findings.md` (NAT endpoint table), `preswap-isolation/orchestrator-cleanup.md` |
| W3 | Wording corrected: "the attacker's OS never runs" is false. Backend-owned files fixed in `211856e`; other owners' files fixed by the orchestrator on main in `f0ddf39`. | `README.md` (Security model), `iso/rootfs/etc/bd/egress.nft` header, `docs/real-mode-findings.md` |
| B2 | A real-mode control plane reports `vultr: real`. | `b3/healthz-before.json`, `b3/healthz-after.json` |
| B3 | One real case end-to-end through the control plane (`BD_REAL_MODE=1`, backend on bd-cp at reserved IP 207.246.91.37 inside the VPC, code `git archive 098f535`): `POST /cases` on shop-prod (created from snapshot `ef199a06`), then snapshot `7b0888f2`, then twin `a65420d5` from ISO plus snapshot, then the driver's out-of-band ESP swap (00:52:11), then sealed registration over the VPC (`POST /twin/register` 200 from 10.1.96.4). | `b3/run.log`, `b3/backend-journal.txt`, `b3/esp-swap.txt`, `b3/findings.json`, `b3/api/` |
| B3 | Seal: `disk_read_only` true (`/dev/vda2 on /mnt/disk: ro,nosuid,nodev,noexec`), `egress_blocked` true (5/5 probes timed out: 1.1.1.1:53, 8.8.8.8:53, 1.1.1.1:443, 9.9.9.9:80, 208.67.222.222:443). | `b3/case-detail.json` (`seal`), `b3/findings.json` |
| B3 | Real two-model investigation: planner `glm-5.3-flash`, solver `glm-5.3`, both picked from the live model list. It ran 9 steps on the twin under gVisor (`runtime=runsc network=none read-only-rootfs`). The bundle carries the twin's real stdout, not the recorded fixture text (`78b5e66`). | `b3/inference-models.json`, `b3/inference-model-smoke.json`, `b3/case-detail.json` (`steps`), `b3/bundle-case-0001.zip` |
| B3 | 2 evidence-linked findings (medium): a hidden beacon-pattern script `/usr/local/bin/.bdrv`, and a PE staged as `/tmp/bd.efi`. A report was produced. | `b3/case-detail.json` (`findings`), `report.json` in the bundle |
| B3 | No production change without approval. The 2 containment actions (`quarantine_firewall`, `stop_instance`) stayed `proposed` (`approved_by` null, `applied_at` null). Blast radius 0/0/0. | `b3/case-detail.json` (`actions`, `blast_radius`), `case_log.json` in the bundle (seq 33-34) |
| B3 | Close returned 200 `closed`. Bundle returned 200 with `snapshot_id.txt`, `file_hashes.json`, `case_log.json` and `report.json`. The 38-entry hash chain verifies (`contracts.hashing.verify_chain`, first bad seq none). | `b3/close-response.json`, `b3/bundle-case-0001.zip`, `b3/findings.json` (`bundle`) |
| B3 | Twin gone after close: `GET /v2/instances/a65420d5` returns 404. The case snapshot was deleted by the driver. | `b3/findings.json` (`twin_get_after_close`, `case_snapshot_deleted`), `b3/api/` |
| FINAL | The account is back to the kept baseline: 0 instances, $0/hr compute. | `final-sweep-dry-run.txt` (burn line below) |

FINAL sweep burn line (`scripts/vultr_sweep.py --dry-run`, 2026-11-18 ~01:12 EST):

```
burn: $0.0000/hr compute (0 instances on the account); snapshot storage $0.0003/hr (3 snapshots); 0 NAT gateways on the account (billed hourly, not priced here)
```

Kept: snapshots case-0001 `8b5f79c3`, case-0002 `e6cb532a` and shop-prod `ef199a06`;
VPC `ab6a9e85`; ISO `97962862`; reserved IP `b062913e` (207.246.91.37, kept via
`BD_CP_RESERVED_IP_ID` for reruns and Gate 3; released only by `--release-reserved-ip`).

## Measured limitations (Gate 3 quantification targets, not blockers)

1. **`custom_script` language.** The planner wrote shell, but the sandbox runs Python
   (`python3 /work/script.py /mnt`), so step 5 exited 1 with a `SyntaxError`. Fixed
   after B3 in `377963e`: the planner prompt now states the language. Gate 3 remeasures
   it; B3 was not rerun. Evidence: `b3/case-detail.json` (step 5 `stderr`).
2. **Detonation target.** The planner detonated `/tmp/bd.efi`, a PE/EFI file
   (`Exec format error`, exit 2), not the ELF beacon `/usr/local/bin/.bdrv`. So **no
   DNS capture** happened this run. Evidence: `b3/case-detail.json` (step 8).
3. **Coverage.** Only 2 planted indicators became findings. The rogue
   `/root/.ssh/authorized_keys` entry was read by `auth_scan` (step 2 stdout) but not
   flagged (`report.rogue_ssh_keys` is empty). Evidence: `b3/case-detail.json`,
   `report.json` in the bundle.
4. **Rationales are not shown by `GET /cases/{id}`.** This corrects my earlier report
   of "empty planner rationales". The model's rationales are present in the
   hash-chained log (`step_started` events in `case_log.json`; step 1: "Establish a
   trusted baseline of OS, ...") but the steps table stores rationale as event-only
   metadata, and the API projects `rationale=""` (`backend/backend/db.py:97,104`).
   This is an API visibility gap, not a model gap.
5. **Sweep matched by description, not id.** In run 4 the case's own snapshot
   `a4d1984f` had the same description, "body-double case case-0001", as the kept
   case-0001 snapshot `8b5f79c3`. `PROTECTED_SNAPSHOT` matches descriptions, so the
   sweep kept it and it was deleted by id manually. The B3 driver now deletes its
   case's snapshot by id. Recommendation: protect the kept snapshots by id. Evidence:
   `b3/run4-register-timeout/`.
6. **Sweep did not own the backend's firewall groups.** Run 7 left the unapplied
   quarantine group `b4d15ab5` ("bd quarantine case-0001"). The backend creates it when
   the action is proposed, and nothing deletes it if the action is never applied. The
   old ownership marker classified it as "other". The sweep now owns unattached
   "bd twin " and "bd quarantine " groups (`175e58a`), and the group was swept. The
   backend-side leak itself (delete an unapplied quarantine group on close) is open.

## B3 attempts (each archived with its cause; all cleaned to zero)

| run | failure | fix |
|---|---|---|
| 1 `b3/run1-unauthorized-ip/` | Allowlist check used `GET /v2/regions`, which is public and returns 200 with no key: a false positive. The backend then got 401 "Unauthorized IP". | `128ab10`: check `/v2/account` |
| 2 `b3/run2-allowlist-timeout/` | Reserved IP not yet on the API access-control list (30 min gate expired). | user added 207.246.91.37/32 |
| 3 `b3/run3-shop-locked/` | Snapshot-created shop-prod was `active` but still locked: 400 "Cannot take snapshot while server is locked". | `ba59b2a`: wait for `server_status=ok` |
| 4 `b3/run4-register-timeout/` | Driver set `BOOT_TIMEOUT_S`, but the registration wait reads `REGISTER_TIMEOUT_S` (300 s default). Also the hour-long POST response was lost in the SSH tunnel. | `57a439d`: `REGISTER_TIMEOUT_S=1800`, short-connection polling, keepalive tunnel |
| 5 `b3/run5-token-underscore/` | The ISO rejected `user_data`: the token from `token_urlsafe` contained `_`, which the ISO's `SAFE_ID` forbids (~40% of tokens), so the sealed boot never configured its VPC interface. | `757e28a`: `new_reg_token()` = hex, test pinned to the ISO's `SAFE_ID` |
| 6 `b3/run6-investigator-kwargs/` | Registered. Then `InvestigatorImpl(planner=, solver=)` raised `TypeError`: forensics had landed `planner_model=/solver_model=`. | `098f535`: correct kwargs; test builds the real class |
| 7 `b3/` | **PASS** | |

Spend: every run used vc2-1c-1gb instances (at most 3 at once) for under 1 h each, plus
the reserved IP. That is well under US$1 of the US$20 cap.

## Security review follow-ups (orchestrator-approved, after B3)

- `39882b1`: Evidence paths are JSON-escaped in model prompts and wrapper labels. DNS
  names are charset-validated (otherwise `hex:`). `case.reason` is wrapped and
  pre-scanned. Required triage (`os_facts`, `persistence_scan`) runs code-side before a
  planner `done` is honoured; time and step budgets still win.
- `9af35ec` + `175e58a`: `InvestigatorImpl` ids are case-scoped. Evidence starts after
  the control plane's snapshot record (`<case>-ev-002`), because `ev-001` collided after
  scoping and the review caught it. The two-case-one-DB regression test fails on the old
  ids (`UNIQUE constraint failed: steps.id`) and passes now.
- Test state at the end: backend 114 passed; forensics 86 passed / 2 skipped, plus
  `test_f07_detonate::test_runner_resolver_sinkholes_and_logs`, which is flaky on this
  Windows host (localhost UDP). It fails identically on unchanged HEAD code and passes
  on rerun. Scripts: 24 passed. B3 itself ran on `098f535`, before these follow-ups.
