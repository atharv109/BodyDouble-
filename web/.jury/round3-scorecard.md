# Body Double (localhost:4400): jury score, round 3
Estimate, not affiliated with Awwwards. Independent critic (fresh blind subagent, given only screenshots and audit output), covering 2 shot page types (home `/`, 404) plus the operator console `/console` (gate and inside), 2026-11-08.
Evidence: `.jury/round3/shots/`, `.jury/round3/console/`, `.jury/round3/audit.txt`, `.jury/round3/audit-console.txt`.

**The idea, as the critic read it:** Body Double is an incident-response tool for Vultr. It snapshots a server that looks hacked, investigates a sealed copy (the "twin"), and changes the real server only after a human approves. The "production untouched / twin sealed" pairing appears throughout: the hero (d-01), the sticky case sidebar (d-03 to d-07), the 404's "twin · empty", and the console gate.

**Critic overall: 6.8** (0.4 Design + 0.3 Usability + 0.2 Creativity + 0.1 Content, on the critic's strict scale)
**Jury estimate: about 7.9** (critic + 1.1, an offset measured on two recent Sites of the Day; it has not been measured on weaker sites)
**Band, from the estimate:** Site of the Day range (7.2 and up)

| Criterion | Score | Evidence |
|---|---|---|
| Design (40%) | 7 | A clear type system: a heavy sans for headings and mono for state words. A limited palette: near-black, bone, and gold kept for the twin and the approval. Memorable frames: the twin diagram (d-01), "Blast radius: zero." (d-06), the gold Approve block (r-02-mid), and the firewall value turning gold in the sticky card (d-05). The 404 stays on concept. Against: large dead areas (the empty Wall 2 box in d-05, about 300 px blank under "Seal and verify" in m-03, the empty Wall 3 box in m-04). The hero diagram floats low-right, leaving dead space (d-01). The incidents column is cramped (d-02). Watch and Investigate carry equal weight (console/d-02). |
| Usability (30%) | 6 | LCP 564 ms on the throttled phone, a skip link first, reduced motion clean, and the console nav lands correctly. Against: mobile scroll runs at 27 fps (worst frame 83 ms). The desktop page overflows sideways. The phone header drops "How it works" (m-01). "Console" stays underlined after going back to home (d-92-back). A 401 on every home load, plus 404s and 500s on the console. |
| Creativity (20%) | 7 | The twin concept drives the layout: the sticky "THE CASE" sidebar moves forward with the story, and the production state changes once, at approval. Still, the signature moment is a static two-tile diagram with a scan line. No transition or interaction acts out "the copy". |
| Content (10%) | 8 | Real incidents with sources (NotPetya, SolarWinds), exact API calls, and a real voice ("Model output is data."). One slip: d-10 refers to "the playbook above" with nothing above it. |

| Developer | Score | Evidence |
|---|---|---|
| Semantics/SEO | 6 | One h1 and a unique title on each page. Audit FAIL: a missing URL returns HTTP 200. |
| Animations/Transitions | 7 | The page transition fades and slides behind a gold progress line (d-90). Buttons flood to bone on hover (h-01 to h-03). `noHoverChange` and `colorOnly` are empty. The logo hover is invisible (h-06), the sidebar row only brightens (h-04), and mobile scroll runs at 27 fps. |
| Accessibility | 7 | 0 axe violations, a skip link first, every focus stop visible, and reduced motion clean. The focus ring on "How it works" is clipped (k-03). `contrastNeedsReview` is 8. |
| WPO | 7 | LCP 564 ms, CLS 0.001, JS 168 KB gzipped, page about 182 KB. Mobile scroll runs at 27 fps. The page settles at 3561 ms (desktop) and 4333 ms (mobile), past the 2.6 s budget. |
| Responsive | 6 | Desktop overflow at 1440 (`article.option`, `ul.incidents`, `li.incident`). Console server names break mid-word on the phone (console/m-03). The 404 "twin · empty" label is about 9 px on the phone. The phone nav loses a link. |
| Markup/Meta-data | 8 | 0 audit FAILs and 0 WARNs in this area. |

## Fixes, most score first
1. [Usability/WPO/Anim] Home, phone scroll at 27 fps (worst frame 83 ms). Suspects: the sticky status bar (m-02 to m-06), the looping scan line on the twin, and the reveal observers. Animate only transform and opacity, and pause the scan line when it is off screen.
2. [Responsive/Usability] Home, desktop horizontal overflow (`article.option`, `ul.incidents`, `li.incident`, `h3.t-m`, `p.mt-2`). Give the grid and flex children `min-width: 0`, and wrap long URLs with `overflow-wrap: anywhere`.
3. [Design] Home, boxes left empty while they wait on a scroll reveal: Wall 2 (d-05), under "Seal and verify" (m-03), Wall 3 (m-04), and the missing reason line under "Open a case" (d-10). Reveal earlier (a larger rootMargin), or don't reserve the height before the content is in.
4. [Semantics/SEO] Unknown routes return HTTP 200 (audit FAIL). The server fallback should send status 404 with the existing 404 page.
5. [Usability] d-92-back: "Console" keeps its active underline after the route goes back to home. Reset the nav's active state on every route change.
6. [Design] Hero, d-01: the diagram sits low-right with about 150 px of dead space under it. Raise the diagram so it lines up with the subhead and CTAs.
7. [Usability] Console errors: a 401 on `/api/auth/config` on every home load, and 404s and 500s on `/console` (9 on desktop). Skip the auth call when nobody is logged in, and fix the failing endpoints.
8. [Design/Anim] Weak hovers: the logo (h-06) shows nothing, and the case-sidebar row (h-04) only brightens. Show the gold active tick on hover, and nudge the logo mark.
9. [Accessibility] k-03: the focus ring on "How it works" is clipped on the left. Remove `overflow: hidden` from the nav, or add an outline offset and padding.
10. [Usability/Responsive] m-01: "How it works" is missing from the phone header. Add it back, or add a menu.
11. [Responsive/Design] console/m-03: server names break mid-word ("clean-/control"). Stack the IP under the name. Make Investigate the primary action with the gold fill, so it doesn't weigh the same as Watch.
12. [Responsive] 404/m-01: the "twin · empty" label is about 9 px. Use at least 12 px, not a size scaled with the icon.
13. [Content] d-10: "the playbook above" points at nothing above it, so reword it. The header says "Try it" while the section is called "Infect a server"; use one name for both.

## Measured
- Mobile LCP and CLS: home 564 ms / 0.001; 404 556 ms / 0
- Loader: none. Settled: home 3561 ms desktop, 4333 ms mobile; 404 2335 / 3570 ms
- Scroll FPS: home 60 desktop, 27 mobile; 404 60 / 61
- Serious axe violations: 0 (`contrastNeedsReview`: 8 on home, 1 on 404)
- Overflow: home desktop true; phone false; console false on all viewports
- `noHoverChange` and `colorOnly`: empty. Idle motion: home true (scan line), 404 false
- Console errors: home 1 (401). `/console`: 9 on desktop, 3 on phone, 3 with reduced motion (401 / 404 / 500)
- Audit: 1 FAIL and 0 WARN on each of `/` and `/console` (the 404 status)

Not scored: anything stills can't show (how motion feels, sound). The audit crawled 1 HTML page per run, because the site is a client-routed SPA.
