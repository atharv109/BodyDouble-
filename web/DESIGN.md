# Body Double web: design notes

## Brief
- Subject: Body Double, incident response for small teams on Vultr.
- Audience: the one technical person who gets the 2 a.m. alert; also hackathon judges watching a 90 s video.
- Job: make "production was never touched" visible and believable, then let one human approve containment.
- Four screens (PRD UI): Servers, Case (live), Approve drawer, Close and evidence.
- Stack: React + Vite + TS + Tailwind v4, react-router. Reason: an SPA in front of FastAPI + SSE; no server rendering to earn.

## Concept (picked from three)
1. *Glass wall* (picked): two bodies separated by a pane. Production sits still on the left, the twin works on the right. Anchor: the product's literal promise, "the copy, never the original".
2. Evidence locker: tags, bags, chain-of-custody seals. Lost: reads as a theme, not a tool.
3. Surgical theatre: observation window over an operating table. Lost: gore-adjacent, and it fights "quiet".

```
Idea:        Production stays frozen behind glass while its twin is taken apart beside it.
Metaphor:    an observation room: one side never moves, the other side is all instruments.
Signature:   the seal. When both seal checks pass the twin column's frame closes around it
             (a 1 px line draws the full perimeter) and the state rail locks at "sealed".
Emotion:     calm control. Nothing flashes until something is actually found.
Motion verb: latch. Short travel (4-8 px), fast out, hard stop, no bounce.
Screenshot:  the case screen mid-run: grey untouched prod, brass-lit twin feed, red findings.
```

## System
| Role | Hex | Use |
|---|---|---|
| ground | `#0d0e10` | page |
| panel | `#141619` | columns, cards |
| line | `#262a30` | hairlines, grid |
| ink | `#e7e5df` | text |
| muted | `#8b9099` | labels, meta (AA on ground and panel) |
| agent | `#d6b25e` | brass: anything the agent did or changed (twin state, steps, proposed and applied actions) |
| finding | `#ef5a52` | red: findings only (severity marks, DNS capture card) |

- Type: IBM Plex Sans (UI, 400/500/600) and IBM Plex Mono (evidence, IDs, IPs, hashes, code, API calls).
  Display sizes use negative tracking (-0.02em); labels are 12 px mono, uppercase, +0.06em.
- Grid: 12 columns, 24 px gutter, max 1600 px. Case screen 3 / 5 / 4.
- Radius: 2 px everywhere (cards, buttons, chips). Glass edges stay square.
- Motion: one ease `cubic-bezier(.2,.8,.2,1)`; 160 ms for small, 280 ms for drawers and the seal line.
  New feed items latch in from 6 px below. Reduced motion: all off, content fully visible.
- Idle: the screen is still at rest by decision. It is a live instrument; motion only means "the backend said something".
  The only resting motion is the 1 s pulse on a running step's status dot.

## Composition
```
Servers         Case (live)                                      Close
+-----------+   +--------------+-------------------+-----------+  +------------------------+
| h1 + note |   | PRODUCTION   | TWIN              | FINDINGS  |  | 0   0   0  (blast)     |
|-----------|   | server card  | rail o-o-o-o-o-o  | crit card |  | teardown receipt       |
| row  [Inv]|   | [untouched]  | seal x2           | high card |  | [Download bundle]      |
| row  [Inv]|   | firewall grp | step feed ...     | DNS (red) |  |                        |
+-----------+   +--------------+-------------------+-----------+  +------------------------+
                                  Approve: drawer from the right edge, over the findings column
```

## Decisions
- No loader, no smooth scroll, no WebGL: an ops tool doesn't earn the theatre (awwwards: scale to brief).
- No /anatomy figure: the case screen itself is the live explanation of the mechanism; a drawing would compete with it.
- Red is never used for errors of the UI itself; those use ink on a line-bordered panel.
