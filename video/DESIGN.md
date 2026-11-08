# Body Double — film DESIGN.md

Source of truth: the app's own design tokens (`web/src/index.css`). The film
inherits the product's identity; it never invents a second one.

## Style Prompt

Dark cinematic technical film. Charcoal ground, graphite panels separated by
hairline rules, warm off-white typography, one restrained gold accent for
anything the agent seals or approves, red reserved strictly for attacker
findings. Deep quiet, subtle depth via layered panels and a faint vignette —
no glow abuse. The camera moves slowly and deliberately; the only fast thing
on screen is the terminal cascade. Duplication and containment are carried by
one recurring device: **the seal line** — a 1px gold perimeter that draws
itself closed around the twin, inherited from the app's own
`.seal-frame`/`site-head::after` behaviour. The whole film reads as the
product's night console: what an operator sees at 2 a.m., explained calmly.

## Colors

Roles are exactly the app's tokens (`web/src/index.css`):

| Token    | Hex       | Film role                                            |
| -------- | --------- | ---------------------------------------------------- |
| ground   | `#0b0d0f` | Canvas background, letterbox space                  |
| panel    | `#13161a` | Cards, chips, footage frames                        |
| raise    | `#1a1d21` | Raised surfaces, panel headers                      |
| line     | `#262a30` | Hairlines, dividers, grid                           |
| ink      | `#e7e5df` | Primary type (warm off-white)                       |
| muted    | `#8f949c` | Secondary type, labels, captions                    |
| agent    | `#d6b25e` | Gold — seal lines, approvals, agent actions, ONLY   |
| finding  | `#ef5a52` | Red — attacker findings, DNS capture, ONLY          |

Gold = anything the system did deliberately (seal, propose, apply).
Red = anything the attacker did. Never invert, never introduce a new hue.

## Typography

The app's pairing, both present in the product (`web/src/index.css` fonts):

- **IBM Plex Sans** 400/600 — the human voice: narration captions,
  statements, scene titles. Display sizes 300→600 weight contrast.
- **IBM Plex Mono** 400/500 — the machine voice: tickers, evidence excerpts,
  API calls, data labels, `tabular-nums` on every number column.

Tension: human explanation (sans, proportional) vs machine evidence (mono,
fixed). The register switch IS the story: a person reading what a machine
recorded. Neither font is on HyperFrames' banned list.

Dark-background compensation: line-height +0.05 over web values; display
sizes get `letter-spacing: 0.01em`; body text sits at weight 400 (never lighter).

Sizes for rendered video (minimums per house rules): headlines 60–130px,
statements 22–28px, mono data 16–20px, captions 26px+.

## Motion Language

Inherited from the app's CSS, not invented:

- **Latch** (`--ease-latch: cubic-bezier(.2,.8,.2,1)`): short travel
  (6–24px), hard stop, 160–280ms. Every element enters this way.
- **Seal-line draw**: a gold 1px line sweeping left-to-right
  (`clip-path: inset(0 100% 0 0)` → `inset(0 0 0 0)`), 600–760ms. Used as the
  primary scene transition — scenes are *opened under the seal line*, exactly
  like the app's view-transition (`vt-wipe` + `seal-line` keyframes).
- **Perimeter seal**: the gold rectangle closing around the twin frame
  (`.seal-frame`), reserved for the sealed/approved beats.
- **Pulse-dot**: `steps(2)` 1s blink for "running" states; never smooth glows.
- **Slow push**: held end-states get a 1.0→1.04 scale drift over the full
  hold, max. That is the only camera move on real footage.

## Scene transitions

- Primary (60–70%): **seal-line wipe** — old scene holds fully visible, gold
  line draws across, new scene revealed behind it. Calm/clinical energy.
- Accent for section turns: 3–4 **staggered panel blocks** (the terminal
  panes) sliding 24px with the latch ease.
- Outro: plain crossfade to ground, 0.6s.
- Never: glitch, VHS, chromatic aberration, whip pans, zoom-throughs.

## What NOT to Do

- No neon, matrix rain, scanlines-for-atmosphere, or generic hacker imagery.
- No fake product UI. Real screens come from `video/clips/` recordings; HTML
  only for title, architecture diagram, callouts, captions, end card.
- No red or gold decoration — both hues mean something specific (attacker /
  agent) and appear nowhere else.
- No full-screen linear gradients on dark ground (H.264 banding); depth comes
  from layered panels, radial vignette at ≤8% opacity, hairlines.
- No two-element "slideshows": every scene has hierarchy — one dominant
  element, supporting text, breathing room.
- No `repeat: -1` animations, no `Math.random()`, no exit animations before a
  transition (the wipe is the exit).
- Fonts never smaller than the sizes above; if a line doesn't fit, cut the
  line, not the size.
