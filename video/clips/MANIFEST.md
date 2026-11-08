# Clip manifest — video/clips/

All clips are real recordings of the running product (1920×1080, 30 fps,
h264, no audio). Source: Playwright capture at 3840×2160 dsf2, downscaled
lanczos. App state machine, event payloads and end states verified against
the backend API after capture (`GET /cases/case-0001`: closed, 6 findings,
quarantine PATCH → 202 applied, blast radius 0/0/0).

Capture stack (isolated from the shared :8000 worker server):
backend `uvicorn backend.app:app --port 8010` with `POLL_INTERVAL_S=2.5`
(fake-mode default 0.05 s would flash the state walk past in ~1 s; only the
poll cadence changes — see ../claims.md), frontend `vite preview --port 4273`
with `API_TARGET=http://localhost:8010`, production build (no dev chrome).
Case id on screen is `case-0001` in every case-screen clip.

| Clip                      | Len  | Content                                                                 | Pass / trim     |
| -------------------------- | ---- | ----------------------------------------------------------------------- | --------------- |
| `console-alert.mp4`        | 2.6s | `/console` servers list; shop-prod row hover                            | A 0.6–3.2       |
| `console-open-case.mp4`   | 5.2s | Investigate dialog; reason typed; Open case clicked; busy state         | A 3.0–8.2       |
| `case-rail.mp4`           | 4.8s | Case screen live: rail walks snapshotting → restoring → sealed          | B 0.7–5.5       |
| `case-seal.mp4`           | 4.4s | Sealed: scroll to bottom row; both checks `[ ok ]`; gold perimeter draws | B 5.3–9.7       |
| `case-steps.mp4`          | 3.1s | Triage steps cascade in the commands pane                               | B 8.9–12.0      |
| `case-findings.mp4`       | 4.3s | Report at scroll 0: six findings, ranked fixes in the AI pane          | B 10.6–14.9     |
| `case-injection.mp4`      | 3.5s | Same framing held; zoom source for the AI-note finding card             | B 11.0–14.5     |
| `case-dns.mp4`           | 5.1s | Sandbox pane: `beacon.c2.example → sinkhole`, meters 0 / 0              | B 14.5–19.6     |
| `approve-flow.mp4`        | 7.4s | Approve drawer: PATCH call shown, tick, Approve click, 202 response      | B 19.0–26.4     |
| `close-blast.mp4`         | 8.7s | Close screen: outlined zeros → Destroy → confirm → solid 0 0 0, closed  | B 25.8–34.5     |
| `console-alert-auto.mp4`  | 4.0s | Console with a real sensor alert; Case chip clicked (auto-opened case)  | C 0.4–4.4       |
| `case-auto.mp4`           | 4.6s | The alert-opened case screen (reported)                                | C 4.3–8.9       |

Passes (capture scripts in `../capture/`, `capture.mjs` + `markers.json`):

- **A** — human entry: console, Investigate on shop-prod, reason
  "CPU at 100% overnight, unknown process.", submit. Cut during the busy
  state; the UI case in fake mode auto-closes, so progression footage comes
  from B.
- **B** — full story: `POST /dev/fake-case` fired un-awaited so the browser
  attaches to the live SSE stream and the case walks on camera; then the real
  UI approval (one action), real teardown click, real close screen.
- **C** — sensor story: `POST /dev/infect` with all five attacks; the alert
  lands in the console inbox and its case opened itself.

Not committed: `../capture/raw/*.webm` (15 MB intermediates, regenerable via
the scripts).
