# Worker: backend (Gate 2)

You own: `backend/`, `scripts/`, `evals/`, `docs/`, `iso/`. Never edit `contracts/`
or `.claude/`, and never commit anything outside what an item below names.

## Context (Gate 1, already merged to main)

`docs/real-mode-findings.md` + `scripts/s5_twin.py` + `evals/results/real-mode/` hold
the live-tested twin flow (create-from-ISO → VPC IP patch → register → restore →
ISO re-insert → ESP swap → sealed boot → 3/3 jobs). Read that file first — the
findings you must respect are listed there (use `curl.exe`, not
Invoke-RestMethod; metadata is `/v1.json` + `Metadata-Token: cloudinit`; attach is
`POST /v2/instances/{id}/iso/attach`; reboots: use guest `systemctl reboot`).

Secrets come from `%USERPROFILE%\.bd-secrets.env` via the existing `load_secrets()`
pattern. Never print, commit, or ISO a secret value. Cost cap: US$20 of Vultr usage
total — tear down everything you create in `finally`, run `scripts/vultr_sweep.py`
after every session, and stop with a QUESTION if anything would exceed the cap.

## Before every item

Commit after each item with the item ID in the message.

## Checklist

- [ ] B0: Port the `RealVultr.request()` allowlist hardening (method+host pin,
      no redirects) from `C:\Users\athar\OneDrive\Desktop\vultr\contracts\vultr.py`
      into this repo's VultrClient so every real call is allowlisted. Done when:
      a unit test proves a disallowed host/method/redirect is refused.
      Test file: `backend/tests/test_vultr_client_allowlist.py`
- [ ] B1: `BD_REAL_MODE` env switch: unset = existing fake behavior untouched;
      set = all instances/snapshots/VPC/ISO calls go to the real Vultr API.
      Done when: existing fake-mode tests still pass and real-mode client
      construction is covered by tests (no live calls in tests).
      Test file: `backend/tests/test_real_mode_switch.py`
- [ ] W1 (reviewer-required, live): measure egress in the pre-swap window itself,
      boot→ESP-swap, not just after the seal. During the run-13-style flow, from
      the restored clone (which is briefly Ubuntu with its public IP) run
      outbound probes to a listener outside Vultr (operator machine or public
      endpoint), with timestamps, before the swap completes. Done when:
      `evals/results/real-run-01/preswap-egress/probe.txt` has ≥3 timestamped
      outbound probes with results and a one-paragraph verdict.
- [ ] W2 (reviewer-required, live): verify against the live API — not guessed —
      whether the twin can come up with **no outbound path**:
      (a) create attached only to an isolated VPC with no public IPv4
          (`POST /v2/instances` schema check + live attempt in this account);
      (b) any API-supported way to keep the instance powered off / network-dead
          until after the ESP swap.
      Done when: `evals/results/real-run-01/preswap-isolation/findings.md`
      records exactly what the API accepted/rejected, with saved responses
      under that folder, in the style of `real-mode-findings.md`.
- [ ] W3: if and only if W2 proves neither option works, fix the claim wording
      everywhere it appears: README and any "attacker's OS never runs" line —
      state plainly that the clone's own OS runs for up to ~39 s after restore,
      possibly with outbound public IPv4, and that the 5/5 egress-blocked
      measurement applies to the sealed ISO boot only. Also revise the
      `iso/rootfs/etc/bd/egress.nft` header text. Quote W1's verdict.
- [ ] B2: `/api/healthz` reports `"vultr":"real"` while a real-mode run is live
      (and `"vultr":"fake"` otherwise). Done when: endpoint test + the real
      run logs show it. Test file: `backend/tests/test_healthz.py`
- [ ] B3 (the gate): run ONE full real case end-to-end with the real API,
      driven through the control plane (BD_REAL_MODE=1), reusing the run-13
      flow. Done when `evals/results/real-run-01/` contains: the case bundle
      verifying, `GET` on the twin ID returning 404 after close,
      `healthz` real logs, the job results (os_facts, persistence_scan,
      detonate under runsc), and a sweep output showing nothing left but
      snapshots case-0001/case-0002/ef199a06, the VPC, and ISO 97962862.
- [ ] FINAL: `scripts/vultr_sweep.py` dry-run; paste its burn line in your
      final message. Then write `evals/results/real-run-01/SUMMARY.md`
      (claims → evidence-file mapping, same style as Gate 1).

## Task list order

B0, B1, B2 (offline, tests only) → one instrumented live run covering W1+W2
evidence first, then B3's case in the same cycle where possible → B3 →
W3 (if needed) → FINAL.

## Rules

- Long Vultr drivers: launch detached (`Start-Process` python, log to file),
  never as a foreground child.
- If stuck >30 min, write `QUESTION: ...` and stop. Never guess an API shape;
  probe it live and save the response.
- Keys: from `.bd-secrets.env` only. Never in the ISO, repo, or stdout.
- Do not touch snapshots `case-0001` / `case-0002` / `ef199a06`, the existing
  VPC, or ISO 97962862 — sweep must keep them.
