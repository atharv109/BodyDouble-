# Plug and play: sensors, auto-cases, choose the fix, interactive demo

Date: 2026-11-08. Owner: Atharv (approved "do your recommendation"). Contracts: `contracts/` at the
commit that adds `SensorSignal`, `Alert`, `Attack`, `InfectRequest` (read `models.py` bottom section,
`endpoints.py` last rows, `hashing.sensor_signature`).

## Why

The site reads as a concept: a visitor sees one recorded case, and a real user has no way to say
"watch my servers and tell me when one is hacked". Atharv wants: put a sensor on a server when it is
deployed; when it trips, Body Double copies the server and investigates; the user fixes it with our
recommended option or their own.

Scope change, decided by Atharv: the PRD non-goal "detecting the breach" is narrowed. Body Double now
ships a minimal tripwire sensor and webhook intake (the PRD P2 "alert intake" item). It still does
**no** automatic remediation.

## Parts

1. **Sensor** (forensics, new `sensor/`): POSIX `sh` installed by one command or a Vultr startup
   script; a systemd service. Every 30 s it compares a baseline of cron files, `authorized_keys`,
   and system binaries (sha256), and outbound TCP destinations (`ss`). A change -> one signed
   `SensorReport`. Heartbeat every `HEARTBEAT_EVERY_S`. Push-only: no listening port, never runs
   anything it receives, ignores response bodies. Uses only `sh`, `sha256sum`, `ss`, `curl`, `openssl`.
2. **Alert -> auto case** (backend): `/sensors/*`, `/alerts/*` per `contracts/endpoints.py`. A
   verified alert opens a case (reason = the alert summary, quoted) or attaches to the live case for
   that instance, and the case runs to `reported` and stops. Silence for `HEARTBEAT_LOST_S` raises
   a `heartbeat_lost` alert from the control plane, which also opens a case.
3. **Choose the fix** (backend + web): one agent action is `recommended`; the others are shown as
   alternatives; the operator may add their own (`CustomActionRequest`: a menu kind or
   `manual_plan`). Everything still goes through Approve. `manual_plan` is recorded, never executed.
4. **Interactive demo** (backend + web): `POST /dev/infect {attacks}` (fake mode). The visitor picks
   which attacks to plant; the fake sensor fires; the case auto-opens and replays only the chosen
   attacks' findings (`ATTACK_FINDINGS`). No attacks = clean control, zero findings.
5. **Story site, round 3** (web). Atharv: "the site still looks boring, remove unnecessary texts and
   make more animations, it should be like storytelling". The interactive demo replaces "Try it" as the
   climax. All visual decisions remain the skills' (`/awwwards`, `/anatomy`, `/jury`).

## Safety rules (each is a test)

- Alerts are untrusted data: an alert can start a case, never propose, approve or apply an action.
- Bad signature -> 401; `sent_at` outside `SENSOR_CLOCK_SKEW_S` -> 401; reused nonce -> 409;
  over `ALERTS_PER_INSTANCE_PER_MIN` -> 429; unknown instance -> 401 (no enumeration).
- Sensor tokens are stored hashed; enrolment returns the token once.
- `CustomActionRequest` never carries an API path or body; the backend builds them; containment still
  passes `check_raw_call`. `manual_plan` makes no API call.
- `/dev/infect` is 404 in real mode, like `/dev/fake-case`.
- The sensor contains no secret but its own token (file mode 0600, root-owned).

## Non-goals

Automatic containment; memory capture; Windows; a full EDR. The sensor is a tripwire, not a scanner.
