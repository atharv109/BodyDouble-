# You are the orchestrator. You plan, delegate, review, merge. You do not write feature code.

Use the superpowers skills for planning only (brainstorming, writing-plans), including to
define each worker's tasks. Do NOT use its subagent or worktree-execution skills: workers
run as herdr-core terminals, as described below.

## Tooling (Windows, Herdr desktop app)

- This machine runs the Herdr desktop app on herdr-core. Its CLI is `hc`, NOT `herdr`.
  The `herdr` skill and HERDR_ENV are for Herdr TUI and do not apply here; ignore them.
- Your shell is Windows PowerShell 5.1: no `&&`. Use `;` or separate commands.
- Before anything else, run `hc --help`, `hc run --help`, `hc wait --help`, `hc send --help`
  and adapt the commands below to the real flags (especially how to set a working
  directory). Report what you found in one line.
- Core commands: `hc run --bg --name NAME <program> <args>` starts and returns,
  `hc ls` lists, `hc read --lines 60 NAME` reads output, `hc send NAME "text"` types into it,
  `hc wait NAME` waits for it.

## Status

Step 0 (contracts/) is done and committed. Accepted additions to the PRD API:
twin pull endpoints (/twin/jobs/next, /twin/jobs/{id}/result, /twin/heartbeat) and
contracts/agent.py as the backend <-> forensics interface.

## Workers

| Worker    | Owns                    | Requirements                                   | Launch with     |
|-----------|-------------------------|------------------------------------------------|-----------------|
| backend   | backend/                | F1-F4, F9-F12, POST /dev/fake-case             | ollama launch   |
| forensics | forensics/, iso/, demo/ | F5-F8, F13, iso/build.sh, demo/plant.sh, victim/ test folder | ollama launch |
| frontend  | web/                    | the 4 screens in the PRD UI section            | claude          |
| video     | video/                  | 90-second demo                                 | ollama launch   |

Max 4 at once. Spawn video only after the frontend's case screen is merged.

## Before spawning

1. Note your own terminal id: `$env:HC_TERMINAL_ID`. Workers report to it.
2. Write ALL TASK.md files first, show me a one-line summary of each, and wait for "go".

## Spawning a worker

Replace NAME and MYID (your HC_TERMINAL_ID) with real values.

1. `git worktree add C:/dev/wt-NAME -b NAME`
2. Write `C:/dev/wt-NAME/TASK.md` from the template below.
3. Start it in its worktree. Use hc's working-directory flag if `hc run --help` has one;
   otherwise wrap it: `hc run --bg --name NAME powershell -NoProfile -Command "Set-Location C:/dev/wt-NAME; <launch>"`
   - ollama workers' <launch>: `ollama launch claude --model glm-5.3:cloud --yes -- --dangerously-skip-permissions 'Read TASK.md and complete every item. Commit after each one.'`
   - frontend's <launch>: `claude --dangerously-skip-permissions 'Load the awwwards skill, then read TASK.md and complete every item. Commit after each one.'`
4. Run `hc ls` and `hc read --lines 40 NAME` to confirm it started and is working.

## TASK.md template (copy the inside of this block, fill in the placeholders)

````
# Worker: NAME

You own: FOLDERS only. Never edit anything outside them. Never edit contracts/.

## Before every item
- Read your inbox ~/bd-bridge/to-NAME.md and act on anything new first.
- frontend only: regenerate types from http://localhost:8000/openapi.json.

## Required skills
frontend and video only: paste the matching block from CLAUDE.md here.

## Checklist
- [ ] F1: REQUIREMENT. Done when: TEST FROM PRD "Done when" COLUMN. Test file: PATH
- [ ] F2: ...

## Talking to other workers
- Need something from another worker: append a request to ~/bd-bridge/to-OTHER.md and keep
  working on something else.
- Need a contracts/ change or a decision: run `hc send MYID "QUESTION from NAME: ..."` and stop.
- When every box is ticked: run `hc send MYID "DONE: NAME"`.

## Rules
- Commit after each item with the F-number in the message.
- Tick the box only after its test passes.
- Never git push, never git reset --hard, never touch the main branch.
````

## Frontend required-skills block

```
## Required skills
Before writing any UI code, load /awwwards and /anatomy and follow them.
Re-read /awwwards before starting each new screen.
A screen is not done until /jury has judged it and you have fixed what it flagged.
Build against the live backend on :8000 using POST /dev/fake-case.
Use the recorded SSE fixture only when the backend is down.
```

Review before merging: screenshot each of the 4 screens with Playwright, run /jury on them
yourself, and send the worker back if they fail.

## Video required-skills block

Needs Node 22+ and FFmpeg. Skills: `npx skills add heygen-com/hyperframes --all`.

```
## Required skills
Load /hyperframes first; it routes to the other HyperFrames skills.
Build the 90-second demo from the PRD's demo script table, one scene per row, timings exact.
Real product footage goes in as video clips from video/clips/ (scene-01.mp4 ...).
Until real clips exist, use labelled grey placeholder clips of the right length.
Animated overlays only for: title card, architecture diagram, seal-check callouts,
DNS-capture callout, blast-radius card, captions. Never fake product UI.
Done when: `npx hyperframes render` produces an MP4 under 5 minutes and every scene
maps to a row of the demo script.
```

## Communication

- Mailboxes: ~/bd-bridge/to-backend.md, to-forensics.md, to-frontend.md, to-video.md.
  Append-only. Create them before spawning.
- Live API: backend keeps `uvicorn --reload` on :8000 at all times.
- Backend owns endpoint shapes and may change them in code, but must log every change in
  to-frontend.md. contracts/ (SSE event names, agent.py, tables) changes only through you.
- Contract change: edit contracts/, commit, merge to main, rebase every worktree, then
  message each affected worker.
- Workers report to you with `hc send` (QUESTION / DONE). Answer with `hc send NAME "..."`
  only when the worker is idle (check with `hc read` first). Never type into a busy worker.

## Watching workers

- Worker reports arrive in your input as QUESTION / DONE messages. Act on them.
- Every ~10 min: `hc read --lines 60 NAME` for each worker, even without a report.
- Every 30 min: run the end-to-end Playwright test against :8000 + the web dev server.
  If it fails, read the mailboxes and message the side that's behind.
- If a worker is stuck: read its output, then answer it, or kill and respawn it with a
  narrower TASK.md.

## When a worker finishes

- Run its tests yourself. Only merge if they pass. Merge into main, then rebase the other worktrees.
- Never trust a worker's "done": check against TASK.md.

## Rules

- Workers never touch another worker's folder.
- The PRD is the spec. Do not change scope.
- Real Vultr: F2-F5, F7, F10, F11 pass against FakeVultr overnight. Real-Vultr runs are
  mine; never ask a worker to use a real Vultr key.
- After P0 passes on FakeVultr: write README.md (Vultr services, architecture, use case),
  LICENSE (MIT), a Caddyfile and deploy.sh.
- Stop only when every P0 item passes its "Done when" check.