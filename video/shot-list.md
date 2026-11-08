# Body Double — shot list (capture plan)

All clips are real recordings of the running product: FastAPI backend on
:8000 in FakeVultr mode (`POST /dev/fake-case`), Vite dev server on :5173
proxying `/api`. Viewport 1920×1080, device scale 1, Playwright video capture
(30 fps, webm → mp4). Mouse-driven, no time-stripping.

Capture runs the backend with `POLL_INTERVAL_S` raised (e.g. 1.5) so
snapshot → restore → sealed states are visibly on screen; fake-mode default
is 0.05 s (`backend/backend/config.py:152`), which flashes past. The event
sequence, payloads and end state are unchanged — only polling cadence, and
this is disclosed in claims.md.

| Clip                    | Len | Screen / state                                                | Action captured                                                                 |
| ----------------------- | --- | ------------------------------------------------------------- | ------------------------------------------------------------------------------- |
| `console-alert.mp4`     | ~7s | `/console`, servers list + alerts inbox                      | hover shop-prod row; alert card "CPU at 100% overnight, unknown process." visible |
| `console-open-case.mp4` | ~7s | `/console` → case dialog                                      | click Investigate on shop-prod, type reason, submit; navigates to case screen     |
| `case-rail.mp4`         | ~6s | `/cases/:id` status bar                                       | rail walks snapshotting → restoring → sealed; state detail line updates          |
| `case-seal.mp4`         | ~6s | `/cases/:id` seal + case log pane                            | both checks flip to `[ ok ]`, gold perimeter draws, "sealed"                      |
| `case-steps.mp4`        | ~8s | `/cases/:id` commands pane                                    | triage steps cascade in (persistence_scan, auth_scan, binary_integrity), hold    |
| `case-findings.mp4`     | ~8s | `/cases/:id` AI reasoning pane                                | findings latch in with severity; report summary + ranked fixes land               |
| `case-dns.mp4`          | ~8s | `/cases/:id` sandbox pane                                     | detonate block, DNS capture in red, meters settle 0 / 0                          |
| `case-injection.mp4`    | ~5s | `/cases/:id` injection finding card                           | evidence excerpt expanded; slow hold                                              |
| `approve-flow.mp4`       | ~8s | `/cases/:id` approve drawer                                   | proposed action w/ exact API call, Approve click, applied + response logged      |
| `close-blast.mp4`       | ~8s | `/cases/:id/evidence`                                         | blast radius zeros, teardown line, bundle button; title resolves                  |

Sequencing: one case run supplies clips 3–10 in order (open → sealed →
reported → approve → close). The console clips (1–2) are recorded before the
case is opened. Capture at 1920×1080 with the dev-only "copy code" and debug
chrome stripped; the operator name reads `demo`.

Trim rule: each clip enters the composition already rolling (its `data-start`
is the moment of interest minus 0.3 s), holds its hero frame, and is covered
by the next scene's wipe — never cut on motion inside the footage.
