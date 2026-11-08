# Body Double Story Site Implementation Plan

> **For agentic workers:** this plan is the frontend worker's TASK.md content. Execute task by
> task in order; tick each box only after its test passes; commit after each task. Visual and
> motion design is NOT in this plan on purpose: it comes from `/awwwards`, `/anatomy`, `/jury`.

**Goal:** Turn `web/` into a production-ready, scroll-driven story site that explains what Body
Double does, why and how, then hands the visitor a live fake-mode case in the existing console.

**Architecture:** The story becomes the landing route `/`, outside the operator gate. The console
moves to `/console`; `/cases/:id` and `/cases/:id/evidence` keep their paths and stay behind the
gate. One site, one design system across story and console, decided by `/awwwards`.

**Tech Stack:** existing Vite + React + Tailwind + Playwright in `web/`; animation/3D libraries
are the builder's choice.

**Spec:** `docs/superpowers/specs/2026-11-08-story-site-design.md` (read it fully first: story
beats, real-world evidence table with source URLs, constraints, production bar).

## Global Constraints

- Edit only `web/`. No backend, contracts or Caddyfile changes (orchestrator adds `/console` to Caddy).
- Every visual decision (concept, theme, palette, type, layout, motion, illustration) comes from
  `/awwwards` (site), `/anatomy` (explanatory figures) and `/jury` (judging). Load `/awwwards`
  before any UI code and re-read it before each task below that changes what is on screen.
- Facts only from `PRD.md`, `contracts/fixtures/` and the spec's evidence table. No invented
  numbers, customers or quotes. Never put a real company's name on the demo case.
- Brand mark: `C:\Users\athar\Downloads\Contained Server Twin Emblem.png` (copy into `web/`).
- Existing `data-testid`s used by the console specs keep their names.
- Before every DONE: `npm run build` passes and every e2e spec passes against the mock.

## Review Focus

1. Reduced motion (`prefers-reduced-motion: reduce`): every beat's content must be visible and
   readable without scroll animation. Test in Task 3.
2. Phone width 390 px: no horizontal scroll, no beat that can only be read by scroll-scrubbing.
   Test in Task 3.
3. WebGL unavailable: the page still tells the whole story. Test in Task 3.
4. "Try it" when `/dev/fake-case` is off (real mode, 404) or the API is down: a clear message,
   no crash, no dead button. Test in Task 4.
5. Deep link to `/cases/:id` with no session: gate first, then that case (unchanged). Test in Task 1.

---

### Task 1: Routes: story at `/`, console at `/console`

**Files:** Modify `web/src/App.tsx` (routes, gate placement); Modify `web/e2e/servers.spec.ts`,
`web/e2e/password.spec.ts` (paths `/` -> `/console`); Create `web/e2e/routes.spec.ts`.

**Interfaces:** Produces route `/` (story, no gate), `/console` (gate -> Servers),
`/cases/:id`, `/cases/:id/evidence` (gate, unchanged). Story root element `data-testid="story"`.

- [ ] Write `routes.spec.ts`: `/` shows `getByTestId('story')` and no operator name textbox;
  `/console` shows the gate, then Servers after sign-in; a fresh context opening `/cases/<id>`
  of a mock fake case shows the gate first, then that case.
- [ ] Run it: FAIL. Move routes and gate. Update the two specs' paths only (assertions unchanged).
- [ ] `npx playwright test`: all specs pass. Commit `web: story route at /, console at /console`.

### Task 2: Brand and design system (from `/awwwards`)

**Files:** `web/public/` (logo, favicon set incl. `favicon.svg` or `.ico`, `apple-touch-icon.png`),
`web/DESIGN.md` (replace the old concept with the `/awwwards` concept for the whole site),
styles/tokens as the skill decides.

- [ ] Run `/awwwards` on the spec's intent and beats; record its concept and art direction in
  `DESIGN.md`. The logo may be recoloured or redrawn as vector per the skill.
- [ ] Apply the design system to the console screens too (one site); console behaviour unchanged.
- [ ] Done when: `npm run build` passes, favicon files exist in `web/dist`, all e2e specs pass.
  Commit `web: brand + design system from /awwwards`.

### Task 3: The story, beats 1-9, with scroll choreography

**Files:** story components under `web/src/story/` (structure is the builder's call);
Create `web/e2e/story.spec.ts`.

**Interfaces:** each beat is a landmark section `data-testid="beat-1"` ... `"beat-9"`, in spec
order; beat 9 contains the button `data-testid="try-it"`.

- [ ] Write `story.spec.ts` (run at 1440x900 and 390x844):
  - `beat-1`..`beat-9` exist, in DOM order, each with an `h2`.
  - Every source URL from the spec's evidence table appears as an `<a href>` on the page (7 URLs
    minimum: the PBS, BleepingComputer x2, TechCrunch, The Register, Microsoft DEV-0537, MITRE
    T1213.005 and Google SUNBURST links).
  - With `page.emulateMedia({ reducedMotion: 'reduce' })`, every beat's `h2` is visible after
    `scrollIntoViewIfNeeded()`.
  - `document.documentElement.scrollWidth <= window.innerWidth` at 390.
  - With WebGL disabled (`--disable-webgl` launch arg or stubbing `getContext('webgl*')` to
    return null via `addInitScript`), all 9 `h2`s are still visible.
- [ ] Run it: FAIL. Build the beats with `/awwwards` (+ `/anatomy` for explanatory figures).
  Copy from the spec; incident claims only as the evidence table states them.
- [ ] Run `/jury` on the story; fix what it flags. Spec passes; all specs pass; build passes.
  Commit `web: story beats 1-9`.

### Task 4: "Try it" hands off to a live case

**Files:** beat 9 component; `web/mock/server.mjs` (add `MOCK_FAKE_CASE_OFF=1` making
`POST /dev/fake-case` return 404); Create `web/e2e/tryit.spec.ts`.

**Interfaces:** Consumes existing `GET /auth/config`, `POST /auth/session`, `POST /dev/fake-case`
(returns `{ id }`). Produces navigation to `/cases/:id`.

- [ ] Write `tryit.spec.ts`: (a) no session: click `try-it` -> gate -> type a name -> lands on
  `/cases/<id>` and the case stream renders; (b) with a session: click `try-it` -> straight to
  `/cases/<id>`; (c) `MOCK_FAKE_CASE_OFF=1`: click `try-it` -> a visible message that the live
  demo is unavailable on this deployment plus a link to `/console`; no navigation, no console error.
- [ ] Run: FAIL. Implement. Run: PASS; all specs pass. Commit `web: try it opens a live case`.

### Task 5: Production metadata

**Files:** `web/index.html`, a build-time step for `sitemap.xml` (builder's choice), `web/public/robots.txt`,
OG image file in `web/public/`, 404 route; Create `web/e2e/seo.spec.ts`.

**Interfaces:** `VITE_SITE_URL` (build-time origin, default `http://localhost:5173` in dev).

- [ ] Write `seo.spec.ts`: `/` has non-empty `<title>`, `meta[name=description]`, `og:title`,
  `og:description`, `og:image` (absolute URL starting with `VITE_SITE_URL`), `twitter:card`,
  `link[rel=canonical]`; `GET /robots.txt` is 200 and references the sitemap; after
  `npm run build`, `dist/sitemap.xml` lists `/` and `/console` under `VITE_SITE_URL`;
  an unknown path renders the 404 page.
- [ ] Run: FAIL. Implement. Run: PASS; all specs pass. Commit `web: production metadata`.

### Task 6: Quality gate

**Files:** Create `web/e2e/a11y.spec.ts` (axe via `@axe-core/playwright`).

- [ ] `a11y.spec.ts`: `/`, `/console` (after sign-in) and a running `/cases/:id`, at 390 and 1440:
  zero `serious` or `critical` axe violations.
- [ ] Production build served by `vite preview`; run the `/jury` audit on it: 0 FAIL except the
  known "missing URL returned 200" (Caddy fixes it in deploy). Commit the scorecard to `web/.jury/`.
- [ ] Live check: with the backend on :8000, `API_TARGET=http://localhost:8000 npx playwright test`
  passes (password-path specs may skip in fake mode).
- [ ] Commit `web: quality gate`; send `DONE: frontend`.
