# Body Double story site: design brief

Date: 2026-11-08. Owner: Atharv. Builder: the frontend worker (web/ only).

## Intent

Today `web/` is a working operator console (4 screens) with no pitch. A judge who lands on it
sees a sign-in form and a server list, and never learns what Body Double is, why it exists or
why it is safe. The site must explain **what we do, why we do it and how we do it**, as a
scroll-driven story, and then let the visitor run a real case in the console.

## Who decides what

- **Atharv decided:** the goal above; the story beats below; scroll-driven animation is the
  medium; the logo below is the brand mark (its colour may be changed to form the theme);
  the result must be production ready.
- **The skills decide everything visual:** concept, art direction, theme and palette,
  typography, layout, motion and scroll choreography, illustration, how each beat is shown.
  The builder runs `/awwwards` for the site, `/anatomy` for any explanatory figure, and
  `/jury` to judge it. The orchestrator makes **no** design choices; nothing in this brief
  is a visual instruction.

## Story beats (content, in this order)

Facts come only from `PRD.md` and `contracts/fixtures/` (the recorded shop-prod case). No
invented numbers, customers or quotes.

1. **What it is:** an incident-response agent for teams on Vultr. When a server looks hacked,
   it snapshots it, investigates an exact copy in a sealed environment, and proposes
   containment for the real server that a human approves. Production keeps running.
2. **The problem:** the 2 a.m. alert at a small team with no IR staff. Two bad options: poke
   the live server (tip off the attacker, destroy evidence, run their malware) or shut it
   down (the business goes offline).
3. **Why a copy, and why the copy never boots:** a booted clone could still call the attacker
   or write to the production database, because Vultr Firewall filters only inbound traffic.
   So the twin boots a forensics ISO, mounts the cloned disk read-only, and runs anything
   suspicious only in no-network containers.
4. **How it works:** the real case flow: open case, snapshot, build the twin on a private VPC
   behind an inbound-deny firewall, seal checks (disk read-only, egress blocked), the agent
   writes and runs triage steps, suspicious files detonate in gVisor with a fake DNS that
   catches the beacon, report with evidence-linked findings, human approves containment,
   twin destroyed and evidence sealed.
5. **Three walls:** the twin's OS never runs; untrusted code runs only in no-network gVisor
   containers; every model output is data until code or a human acts on it.
6. **The attacker's note to the AI:** text on the disk telling an "AI analyst" to close the
   ticket is reported as a finding, never followed.
7. **Blast radius zero:** writes to production before approval, packets out, containers
   left running: all 0.
8. **Built on Vultr:** Cloud Compute, Snapshots, custom ISO, VPC, firewall groups, the Vultr
   API, Serverless Inference, each with its role (see PRD "Architecture and Vultr services").
9. **Try it:** one action that opens a live fake-mode case in the console so the visitor can
   watch it and click Approve themselves.

## Real-world evidence (Atharv: cite these, and theme the demo case on them)

Use in beats 2-3, each with a visible link to its source. Quote only what the source says.

| Point it proves | Incident | Sources |
|---|---|---|
| Shutting down takes the business offline | Colonial Pipeline, May 2021: systems taken offline as a precaution halted the pipeline for six days; fuel shortages across the Southeast | https://www.pbs.org/newshour/nation/major-us-pipeline-halts-operations-after-ransomware-attack , https://www.bleepingcomputer.com/news/security/largest-us-pipeline-shuts-down-operations-after-ransomware-attack/ |
| | MGM Resorts, Sept 2023: casino and hotel systems shut down; about $100M hit to quarterly results (SEC filing) | https://bleepingcomputer.com/news/security/mgm-resorts-ransomware-attack-led-to-100-million-loss-data-theft/ |
| | Change Healthcare, Feb 2024: systems shut down, outages for thousands of providers, some services back only months later; $2.3-2.45B projected cost | https://techcrunch.com/2024/06/21/change-healthcare-confirms-ransomware-hackers-stole-medical-records-on-a-substantial-proportion-of-americans , https://www.paubox.com/blog/change-healthcare-ransomware-attack-projected-to-cost-2.3-billion |
| | Maersk / NotPetya, 2017: 4,000 servers, 45,000 PCs and 2,500 applications reinstalled in ten days; $250-300M cost | https://www.theregister.com/2018/01/25/after_notpetya_maersk_replaced_everything |
| Attackers watch the responders | Lapsus$ (DEV-0537), 2022: joined victims' ongoing crisis-communication calls (Microsoft) | https://www.microsoft.com/security/blog/dev-0537 |
| | Scattered Spider: searched victims' Slack and Teams for intrusion and incident-response discussions (MITRE ATT&CK) | https://attack.mitre.org/techniques/T1213/005/ |
| Malware reacts to being investigated (why the twin's OS never runs) | SolarWinds SUNBURST, 2020: checked for forensic and security tools and went quiet, exited, or disabled them; evaded investigators for about seven months | https://cloud.google.com/blog/topics/threat-intelligence/sunburst-additional-technical-details/ |

**Demo case theming (orchestrator's call, within scope):** the live demo stays the fictional
`shop-prod`. Its planted indicators and recorded data do not change. The story frames it as the
same playbook those incidents document (persistence: cron backdoor; access: rogue SSH key;
hiding: replaced `top`; calling home: the C2 beacon), run against a small team with no IR staff.
Never put a real company's name on the demo case or attribute its data to them.

## Brand mark

`C:\Users\athar\Downloads\Contained Server Twin Emblem.png` (1254x1254 PNG: a rounded frame
containing two overlapping documents, the original and its twin). Copy it into `web/`; a vector
redraw and recolouring are the builder's call.

## Constraints

- Stack stays as is: Vite + React + Tailwind in `web/`. Animation and 3D libraries are the
  builder's choice.
- The story is the landing page at `/`. The console moves to `/console` (Servers);
  `/cases/:id` and `/cases/:id/evidence` keep their paths. The console's behaviour, API
  calls and the password gate stay as they are; its look should belong to the same site.
- No backend or contracts changes. The "Try it" beat uses the existing API
  (`/auth/session`, `POST /dev/fake-case`). In real mode `/dev/fake-case` is off, so "Try it"
  must degrade gracefully there.
- Edits stay inside `web/`. The Caddyfile needs `/console` added to its app-shell routes;
  the orchestrator handles that.

## Decided after the builder check

- **Atharv:** the public demo URL runs the backend in **fake mode** (FakeVultr). "Try it" is a
  real, clickable case for every visitor; real-Vultr runs happen separately.
- **Orchestrator's calls (minor):**
  - The story page at `/` sits outside the operator gate. "Try it" passes through the gate
    once (the visitor types a name, so approvals still carry one), then lands directly on
    the new `/cases/:id`.
  - The site origin is a build-time setting, `VITE_SITE_URL`, used for canonical, sitemap
    and absolute OG/Twitter URLs; deploy fills it in.
  - Updating existing e2e specs from `/` to `/console` counts as passing, provided what
    they check is unchanged.
  - Visitors share one backend; seeing other visitors' fake cases on Servers is acceptable.

## Production ready means

- `npm run build` passes; every existing e2e spec still passes (mock and live :8000); a new
  e2e spec walks the story to the "Try it" action and lands on a running case.
- Works and reads fully at 390 px and 1440 px with no horizontal scroll.
- `prefers-reduced-motion`: all content still reachable and readable without the scroll
  animations. Keyboard reachable, visible focus, no serious axe violations.
- Real content and SEO: title, description, Open Graph and Twitter cards with an image,
  favicon set from the logo, canonical, `robots.txt`, `sitemap.xml`, meaningful 404 page.
- Performance: no layout shift from loading; a mobile LCP the `/jury` audit does not fail;
  heavy assets lazy-loaded; works if WebGL is unavailable.
- `/jury` (the builder's own, then an independent blind critic run by the orchestrator):
  no BROKEN items, audit with 0 FAIL other than the 404 status (Caddy fixes that in deploy).

## Non-goals

- New product features, API changes, or claims beyond the PRD.
- Real-Vultr behaviour (fake mode only here).

## Anti-goals (a failure even if it works)

- Design decisions taken from this brief instead of from the skills.
- Animation that hides the story on mobile or under reduced motion.
- Fake product UI presented as real, or invented metrics.
- Breaking the console flow (Servers, Case, Approve, Close) the demo video depends on.
