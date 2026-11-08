# Body Double story site (local production build): jury score
Estimate, not affiliated with Awwwards. Independent blind critic (fresh subagent, evidence only), 2 page types (home, 404), 2026-11-08.
Pass 2 of 2; pass 1 also scored 7.1 and its fixes went into Tasks 3 to 5.

**The idea, as the critic read it:** a pinned production card stays still on the left and only changes when a human
approves the fix, while the case story about the sealed twin scrolls on the right. (Matches DESIGN.md's concept card.)
**Critic overall: 7.1** (0.4 Design + 0.3 Usability + 0.2 Creativity + 0.1 Content)
**Jury estimate: about 8.2** (critic + 1.1, per calibration.md)
**Band, from the estimate:** Site of the Day range

| Criterion | Score | Evidence |
|---|---|---|
| Design (40%) | 7 | type system and gold-on-black palette (d-01, d-04); "Blast radius: zero" as type-as-image (d-06); designed 404. Lost: empty left lane below the card, nav differed between story and console, hero gap |
| Usability (30%) | 7 | mobile LCP 512 ms, CLS 0, 60 fps, reduced motion clean. Lost: nav differed per page, 3-line phone strip |
| Creativity (20%) | 7 | pinned production card, crossing line at approve (r-02), logo splits into production/twin on first paint |
| Content (10%) | 8 | sourced incidents, exact mount flags and API calls, voice |

| Developer | Score | Evidence |
|---|---|---|
| Semantics/SEO | 6 | only FAIL: unknown URL returns 200 (static preview; Caddy serves the real 404 in deploy) |
| Animations/Transitions | 7 | noHoverChange [], colorOnly []; page change is only a cross-fade |
| Accessibility | 8 | 0 axe violations, skip link first, every focus visible |
| WPO | 8 | LCP 512 ms, CLS 0, 165 KB JS gz, ~177 KB page |
| Responsive | 7 | no overflow, no small targets; phone strip and 404 icon placement |
| Markup/Meta-data | 8 | 0 FAIL/WARN, unique titles, OG/Twitter, canonical, JSON-LD |

## Fixed after pass 2
- One nav on every page ("How it works" added to the console header).
- Phone production strip held to one line (`shop-prod fw-… writes 0`) with a soft bottom edge.
- 404: icon above the headline on phone, readable 404 label; footer Console link aligned to the content edge.

## Not fixed, by decision
- 404 status: deploy (Caddy) returns it; `vite preview` cannot.
- Empty left lane below the production card: production holding still is the concept.
- Route change stays a cross-fade with the header held (View Transitions); no theatrical transition for an ops tool.
