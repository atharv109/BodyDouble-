# Body Double web: design notes (story site + console, one system)

## Brief
- Subject: Body Double, an incident-response agent for small teams on Vultr.
- Audience: the one technical person who gets the 2 a.m. alert; hackathon judges with three minutes.
- Job: explain what it does, why, and how, then hand the visitor a live fake-mode case to approve.
- Assets: the emblem (a frame holding two overlapping documents: the original and its twin), the PRD,
  the recorded `shop-prod` case in `contracts/fixtures/`, seven cited real incidents.
- Stack: the existing Vite + React + Tailwind v4 + react-router SPA, plus GSAP (ScrollTrigger) and Lenis.
  Reason: the console already lives here and the story must share its routes, session and tokens.
- Theatre scaled to a product page: no loader, no WebGL. The craft is type, layout, one scroll
  signature and the latch motion.

## Concept (three territories, one picked)
| | Idea | Anchor | Signature | O/F/Fe/P |
|---|---|---|---|---|
| **A. Formal: two bodies** (picked) | The page has two lanes. Production sits in the left lane and does not move for the whole scroll; everything happens to its twin on the right. One thing is allowed to cross the line: the approved lockdown. | PRD: "the only arrow into production is the snapshot and the approved lockdown" | the emblem's twin peels off the original and seals in its own frame; later one brass line crosses into production and the firewall group changes | 4 / 5 / 4 / 1 |
| B. Name: stunt double | A call sheet: the double takes every dangerous shot so the star walks off set untouched. | the product name | clapper cuts between "take" sections | 3 / 3 / 4 / 3 |
| C. Material: evidence chain | Each beat is a hash-chained log entry; a corner hash re-chains as you scroll. | F12 hash-chained case log | hashes recompute on scroll | 3 / 4 / 4 / 2 (too close to a running-total pattern) |

Picked A: it is the product's guarantee drawn as a layout rule, and it survives to the footer, the
console (which already reads production | twin | findings) and the 404. Stolen from C for a detail:
real sha256 prefixes from the fixture set as evidence marks where a beat quotes evidence.

```
Idea:        Production stays still in its own lane while its twin is taken apart beside it.
Metaphor:    a sealed observation room: one body under glass, its double on the bench.
Signature:   the peel. At the top, the emblem's twin document slides off the original and its
             frame draws shut around it (sealed). Later, at "approve", one brass line crosses the
             gutter into the production lane and the firewall group changes: the page's only
             change on the left.
Emotion:     calm control. Nothing flashes until something is actually found.
Motion verb: latch. Short travel (4 to 8 px), fast out, hard stop, no bounce. Scrubbed motion for the peel only.
Screenshot:  the hero mid-peel: ink original on the left, brass twin sealed on the right, h1 across.
```

## System
| Role | Hex | Use |
|---|---|---|
| ground | `#0b0d0f` | page (the emblem's near-black, neutralised) |
| panel | `#13161a` | lanes, cards |
| line | `#262a30` | hairlines, grid, frames at rest |
| ink | `#e7e5df` | text, the original document |
| muted | `#8f949c` | secondary text, meta (AA on ground and panel) |
| agent (brass) | `#d6b25e` | the twin and anything the agent did or changed |
| finding (red) | `#ef5a52` | findings only |

- Emblem recoloured from the source's mint to brass + ink: the twin is the agent's body, so it wears the
  agent's colour; mint on near-black was the acid-green tell.
- Type: IBM Plex Sans (display 600, text 400/500) + IBM Plex Mono (evidence, IDs, hashes, API calls).
  Display: clamp(2.75rem, 1rem + 7vw, 8.5rem), leading 0.92, tracking -0.045em, optical -0.05em indent.
  Body 17 px / 1.55, measure 60ch. Labels 12 px mono uppercase +0.06em only where they carry data.
- Grid: 12 columns, gutter 24 px, max 1600 px. Desktop lanes: production = cols 1-3 (sticky),
  a hairline between the lanes, twin = cols 5-12. Phone: production collapses to a sticky strip.
- Radius: 2 px everywhere (cards, buttons, chips); the emblem frame keeps its own round corners.
- Motion: one ease `cubic-bezier(.2,.8,.2,1)` (`latch`); 160 ms small, 280 ms drawers and seal line,
  600 ms reveals (6 px travel). The peel is scrubbed. Stagger 40 ms.
- Hover (one treatment per role): buttons invert fill + 2 px lift; nav and wordmark lift with an
  underline draw; inline links keep an underline at rest that rises into a brass band; source links
  nudge their arrow 4 px.
- Idle: a slow scan line passes over the twin document only (the agent reads the copy, never the
  original). gsap ticker, paused off screen, absent under reduced motion. The console stays still at rest
  by decision: it is a live instrument; motion there means the backend said something.
- Transitions: route changes use the View Transitions API with a latch (6 px, 280 ms) cross-fade.

## Composition (desktop | phone)
```
beat-1 hero      [ emblem stage, sticky: twin peels right, frames seal ] h1 over cols 1-9
beat-1 what      lanes start: PROD card sticky (cols 1-3) | statement (cols 5-12)
beat-2 problem   2 a.m. poster line | the two bad options as a split pair, each with cited incidents
beat-3 why copy  statement + inbound-only fact | three moves as a numbered sequence (it is a sequence)
beat-4 how       the 8 case states as a ledger, each with the real artifact from the recorded case;
                 "approve" fires the crossing into the PROD lane
beat-5 walls     three nested frames, outermost to innermost
beat-6 the note  poster: the attacker's note set as quoted evidence with path and hash, flagged
beat-7 blast     data: three giant zeros in tabular figures with their labels
beat-8 Vultr     index list: service | role, full-width rows
beat-9 try it    finale: one action, the fake-mode caveat, link to the console; footer
phone: lanes stack; PROD lane becomes a 44 px sticky strip under the header that changes only at approve.
```

## Decisions
- No loader, no WebGL, no anatomy figure: the lanes and the recorded case are the explanation; a figure
  would compete with the peel (awwwards: one signature). Works without WebGL by construction.
- Every number on the page comes from the PRD, the fixture or a cited source.
- Red is never used for UI errors; those use ink on a line-bordered panel.
