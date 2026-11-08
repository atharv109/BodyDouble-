# Body Double

Body Double is an incident-response agent for small teams running Linux servers on Vultr. When a production server looks compromised, it preserves a snapshot and investigates an exact copy inside a sealed throwaway environment. Production continues serving traffic; containment changes happen only after a human reviews and approves the exact API call.

Built during the event, Nov 3 to 8 2026.

## The use case

A solo developer, agency operator, or small security team should not have to choose between experimenting on a live compromised server and taking the business offline. Body Double turns an alert into a preserved snapshot, a read-only investigation, evidence-backed findings, a proposed containment menu, and an exportable case bundle. The demo story investigates `shop-prod`, catches persistence and a harmless command-and-control beacon, flags an attacker-authored prompt-injection note, quarantines production with approval, and destroys the twin.

## Vultr services

| Service | Role |
| --- | --- |
| Cloud Compute | Runs the FastAPI control plane and the disposable investigation twin. |
| Snapshots | Preserves the suspect disk before investigation and remains evidence after teardown. |
| VPC | Provides the twin's only control-plane path on a dedicated private network. |
| Custom ISO | Boots the trusted forensics environment before the cloned operating system can run. |
| Vultr Firewall | Attaches an inbound-deny group to the twin and applies an approved quarantine group to production. |
| Vultr API | Creates, restores, isolates, contains, and destroys infrastructure through one typed client. |
| Vultr Serverless Inference | Hosts the planner, analyst, and reporter model calls. |

## Architecture

The control plane holds credentials, the database, the case state machine, the hash-chained log, and every Vultr API call. It snapshots the production instance and creates a dedicated VPC and inbound-deny firewall group. The twin boots the Body Double forensics ISO with the copied disk mounted read-only. Its ISO configures default-drop egress and calls back only to the control plane over the VPC.

Suspicious files execute inside gVisor containers with no network, a read-only root filesystem, CPU/memory/PID/time limits, and disposable scratch space. A fake DNS resolver records attempted lookups without letting packets leave. The twin pulls fixed jobs from the control plane; it never receives a Vultr or inference credential.

## How the agent performs real work

Three model roles run through Vultr Serverless Inference:

- The planner selects one tool and its arguments for each next step.
- The analyst turns quoted outputs into candidate findings.
- The reporter explains the accepted findings, timeline, and ranked containment choices.

The model cannot invent capabilities. It selects from a fixed tool list: `os_facts`, `persistence_scan`, `auth_scan`, `recent_files`, `binary_integrity`, `listener_config`, `extract`, `detonate`, and `custom_script`. Code executes only on the twin against the read-only mount. Every step records its rationale, source, output, exit status, and duration; every finding must cite evidence belonging to the case.

Guardrails enforce step and detonation budgets, time and resource limits, evidence excerpt truncation, finding-to-evidence integrity, fixed severity rules, and a code-built containment menu. Text addressing an AI is treated as hostile evidence and becomes an injection finding rather than an instruction.

## Security model

- The attacker's operating system never boots: the preferred create call supplies both snapshot and ISO; the fallback creates ISO-first and restores the snapshot while the ISO remains attached.
- The copied disk is mounted read-only and untrusted execution is isolated in no-network gVisor containers.
- The twin has default-drop internet egress and communicates over its case VPC only.
- Registration uses a one-time token delivered through instance metadata. Twin endpoints require a short-lived session and a source address inside the case VPC.
- Human endpoints reject case-VPC source addresses. Real mode requires `BD_OPERATOR_PASSWORD`; model or twin traffic cannot mint an operator session.
- Production changes require an authenticated approval. The exact request and response are appended to a hash-chained case log.
- Failure and close paths tear down the twin, VPC, and firewall group. The blast-radius summary reports pre-approval production writes, packets out, and containers left running.

## Local development

Prerequisites are Python 3.12+, [uv](https://docs.astral.sh/uv/), and Node.js 22.

```bash
uv sync --project backend
uv run --project backend uvicorn backend.app:app --reload --port 8000
npm --prefix web ci
npm --prefix web run dev
```

Without `VULTR_API_KEY`, the backend uses `FakeVultr`; it never contacts a real account. Mint a demo session with `POST /auth/session {"operator":"demo"}`. `POST /dev/fake-case {}` runs the recorded seven-step story and stops at `reported`, ready for explicit approval and close. Its SSE feed is available at `GET /cases/{id}/stream`.

Run tests with:

```bash
uv run --project backend pytest backend/tests
uv run pytest contracts/tests forensics/tests backend/tests
```

## Deploy to Ubuntu 24.04

Clone the repository onto a fresh Vultr VM, point a DNS name at it, then run:

```bash
sudo ./deploy.sh
sudoedit /etc/body-double.env
sudo ./deploy.sh
```

The first run installs Caddy, PostgreSQL, uv, and Node.js 22; creates the `body_double` database; builds the web application; and installs a hardened systemd service bound to `127.0.0.1:8000`. It creates `/etc/body-double.env` once with mode `0600`. Replace every `CHANGE_ME`, set `BD_DOMAIN`, and rerun. Deployment refuses to enable a real Vultr API key while the operator password is still the placeholder.

Caddy obtains and renews HTTPS certificates automatically. `/api/*` is reverse-proxied to FastAPI with immediate SSE flushing. Only `/` and `/cases/*` receive SPA fallback; other unknown paths return a real 404.

For real infrastructure, configure at least `VULTR_API_KEY`, `VULTR_INFERENCE_KEY`, a 12+ character `BD_OPERATOR_PASSWORD`, a high-entropy `APP_SECRET`, `DATABASE_URL`, and `BD_DOMAIN`. Never put real keys in the repository or the forensics image.

## Evidence and lifecycle

The case stream covers state changes, seal checks, steps, DNS captures, findings, proposed/applied actions, and teardown. `GET /cases/{id}/bundle` exports the snapshot ID, file hashes, report, and verifiable hash-chained case log as a ZIP. `python -m backend.warm_twin INSTANCE_ID` can prebuild a demo twin while preserving the same event sequence when adopted.

Licensed under the MIT License. See [LICENSE](LICENSE).
