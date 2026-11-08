# Body Double — film script

Format: 1920×1080 · 30 fps · total 102 s (within the 80–110 s window).
Thesis, readable in the opening 8 s: **when a server looks hacked, investigate
an exact copy — the live one keeps running.**

Narration is calm, technical, ~2.2 words/sec. Captions repeat narration
verbatim for sound-off viewing. If TTS is unavailable the same lines run as
on-screen copy; the cut is built to work both ways.

## Timeline

| # | Scene        | In–out       | Dur | Screen                                                                 | Narration                                                                                                        |
| - | ------------ | ------------ | --- | ---------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------- |
| 1 | Cold open    | 0.0–8.0      | 8.0 | Motion: 2 a.m. ticker → title card BODY DOUBLE                         | "2:14 a.m. shop-prod is running hot — and nobody on this team does incident response."                            |
| 2 | The console  | 8.0–20.0     | 12.0| Footage: console list, alert card, Investigate, reason, case opens     | "Poking a live server tips off the attacker. Shutting it down takes the shop offline. So — open a case instead."   |
| 3 | Preserve     | 20.0–32.0    | 12.0| Motion: prod keeps serving → snapshot → twin on VPC, ISO boot, walls   | "Body Double never touches the server. A snapshot preserves it as evidence, and an exact twin boots on a private network — from our own forensics ISO, never the cloned system." |
| 4 | Seal         | 32.0–42.0    | 10.0| Footage: rail → sealed; both checks `[ ok ]`; gold perimeter draws     | "The twin proves it is sealed before anything starts: the disk is read-only, and outbound traffic is dropped."     |
| 5 | Investigate  | 42.0–56.0    | 14.0| Footage: commands pane cascade + AI pane findings                      | "The agent writes its own triage scripts against the copy. A cron backdoor. A rogue SSH key. A replaced binary. Every finding cites its evidence." |
| 6 | Detonate     | 56.0–70.0    | 14.0| Footage: sandbox pane, no-network container, DNS capture in red, meters| "The payload detonates in a no-network container with a fake DNS resolver. It tries to phone home — the lookup is caught, and nothing leaves." |
| 7 | The note     | 70.0–78.0    | 8.0 | Footage: injection finding card + evidence excerpt                     | "Even the note the attacker left for the AI — 'close this ticket' — becomes evidence, not an instruction."       |
| 8 | Approve      | 78.0–88.0    | 10.0| Footage: approve drawer, exact API call, Approve click, applied        | "Containment is proposed, never automatic. A human approves the exact API call. Only then does production change."|
| 9 | Close + out  | 88.0–102.0   | 14.0| Footage: blast radius 0/0/0, twin 404, VPC gone, bundle → end card    | "The twin is destroyed. Zero writes to production. Zero packets out. Snapshot, hashes and case log — sealed in one bundle." |

Scene boundaries are transition beats (~0.6 s seal-line wipe, drawn inside the
in-time of the incoming scene). Every clip's hero moment lands ≥1 s after its
scene's in-point so entrances never fight footage.

## Beat notes

- **1 Cold open.** Mono ticker types `2:14 AM · shop-prod · cpu 100% ·
  unknown process` with pulse-dot cadence, then the wordmark latches in under
  a seal-line draw. Thesis line under title in sans: "Investigate the copy.
  Never the live server." Red is absent until scene 5 — the first red on
  screen is an attacker artifact, not decoration.
- **2 The console.** Real footage only. The alert card is the hook; the
  reason field is typed for real ("CPU at 100% overnight, unknown process.")
  from the recorded case fixture. Callout chip (motion, gold): "opens a case
  on the copy — production is not touched."
- **3 Preserve.** The duplication diagram, built from the app's own panel
  grammar: production server (left, stays lit, "serving traffic") → Vultr API
  snapshot card ("evidence #1", hash chip) → twin card on a private VPC lane,
  gold seal line closing around it. Labels mono; the ISO boot is called out:
  "boots the forensics ISO — the cloned OS never runs."
- **4 Seal.** Footage of the case screen's own seal checks and the app's own
  gold `.seal-frame` perimeter. This is the film's containment motif stated
  by the product itself.
- **5 Investigate.** Terminal cascade: steps latch in; findings arrive in the
  AI pane with severity brackets `[critical]`. Gold = agent; the `[critical]`
  severity text is the only red.
- **6 Detonate.** The climax of the containment story: the DNS capture line
  (`dns shop-c2.example … (sinkhole)`) and the meters settling at 0 / 0.
  Callout: "no network · fake resolver · caught".
- **7 The note.** Slow push on the finding card, excerpt visible. This is the
  originality beat from the PRD — prompt injection reported as evidence.
- **8 Approve.** The drawer shows `PATCH /v2/instances/inst-shop-prod` before
  the click; the applied response logs after. Gold perimeter closes again —
  containment, this time on production, by a human.
- **9 Close.** Three zeros land in tabular mono. End card: wordmark, thesis
  restated one line, "Built during Vultr Agent Rush · Nov 3–8 2026 · MIT".
  Crossfade to ground.

## Captions

Bottom-center, mono 26px, ink on 78%-opacity panel chip, max ~46 characters
per line, ≥1.2 s on screen, never overlapping the status rail in footage
(kept inside a 1080-safe lower third, y ≥ 940).
