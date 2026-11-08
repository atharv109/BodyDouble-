// Mock control plane: replays contracts/fixtures when the real backend on :8000 is down.
// Implements the PRD HTTP API + POST /dev/fake-case. Usage: node mock/server.mjs [port]
// MOCK_DELAY=ms between replayed events (default 350). MOCK_FAKE_CASE_OFF=1: /dev/fake-case 404s, as in real mode.
import { createServer } from "node:http";
import { readFileSync } from "node:fs";
import { zipSync, strToU8 } from "fflate";

const PORT = Number(process.argv[2] ?? process.env.MOCK_PORT ?? 8001);
const DELAY = Number(process.env.MOCK_DELAY ?? 350);
const FIX = new URL("../../contracts/fixtures/", import.meta.url);
const SSE_TEXT = readFileSync(new URL("fake_case.sse", FIX), "utf8");
const DETAIL = JSON.parse(readFileSync(new URL("fake_case_detail.json", FIX), "utf8"));

const FIXTURE = SSE_TEXT.trim().split(/\n\n/).map((b) => {
  const f = Object.fromEntries(b.split("\n").map((l) => [l.slice(0, l.indexOf(": ")), l.slice(l.indexOf(": ") + 2)]));
  return { event: f.event, data: JSON.parse(f.data) };
});
// Everything before the first action_applied plays on its own; the rest needs a human.
const AUTO = FIXTURE.slice(0, FIXTURE.findIndex((e) => e.event === "action_applied"));
const TEARDOWN = FIXTURE.find((e) => e.event === "teardown_done").data;

const INSTANCES = [
  { id: "inst-shop-prod", label: "shop-prod", region: "ewr", main_ip: "45.77.10.20", internal_ip: "", status: "active",
    power_status: "running", server_status: "ok", plan: "vc2-1c-2gb", os: "Ubuntu 24.04 LTS x64",
    firewall_group_id: "fw-shop-web", vpc_ids: [] },
  { id: "inst-clean-control", label: "clean-control", region: "ewr", main_ip: "45.77.10.21", internal_ip: "", status: "active",
    power_status: "running", server_status: "ok", plan: "vc2-1c-2gb", os: "Ubuntu 24.04 LTS x64",
    firewall_group_id: "fw-shop-web", vpc_ids: [] },
];

const cases = new Map(); // id -> { detail, log: [{event,data}], subs:Set<res> }
let nextCase = 1;
const sessions = new Set();
const swapId = (o, id) => JSON.parse(JSON.stringify(o).replaceAll("case-0001", id));
const swapInst = (o, inst) =>
  inst.id === "inst-shop-prod" ? o
    : JSON.parse(JSON.stringify(o).replaceAll("inst-shop-prod", inst.id).replaceAll("shop-prod", inst.label));

// Plug and play (contracts/models.py bottom section). The mock keeps it all in memory.
const sensors = new Map(); // instance_id -> SensorStatus
const alerts = []; // newest first
let nextAlert = 1, nextDemo = 1;
const hex = (n) => Array.from({ length: n }, () => Math.floor(Math.random() * 16).toString(16)).join("");
const PUBLIC_URL = "https://bodydouble.example";
function enroll(instance_id) {
  const token = hex(64);
  const now = new Date().toISOString();
  sensors.set(instance_id, { instance_id, enrolled_at: now, last_seen: null, healthy: false });
  const install_command = `curl -fsSL ${PUBLIC_URL}/api/sensors/install.sh | sudo sh -s -- ${PUBLIC_URL} ${instance_id} ${token}`;
  return { instance_id, token, install_command, startup_script: `#!/bin/sh\n${install_command}\n` };
}

// /dev/infect: which fixture findings/actions each planted attack produces.
const ATTACK_FINDINGS = { cron_backdoor: ["fd-01"], rogue_ssh_key: ["fd-02"], replaced_top: ["fd-03"],
  c2_beacon: ["fd-04", "fd-05"], ai_note: ["fd-06"] };
const ATTACK_ACTIONS = { rogue_ssh_key: ["act-2"] };
const ALWAYS_ACTIONS = ["act-1", "act-3", "act-4"];
const ATTACK_SIGNAL = { cron_backdoor: ["file_changed", "/etc/cron.d/sysupdate"], rogue_ssh_key: ["file_changed", "/root/.ssh/authorized_keys"],
  replaced_top: ["file_changed", "/usr/bin/top"], c2_beacon: ["new_outbound", "beacon.c2.example:443"], ai_note: ["file_changed", "/root/NOTE_FOR_AI_ANALYST.txt"] };

/** Keep only the replay events the chosen attacks produce (none = clean control, zero findings). */
function attackFilter(attacks) {
  const fds = new Set(attacks.flatMap((a) => ATTACK_FINDINGS[a]));
  const acts = new Set(fds.size ? [...ALWAYS_ACTIONS, ...attacks.flatMap((a) => ATTACK_ACTIONS[a] ?? [])] : []);
  const evs = new Set(["ev-001", ...DETAIL.findings.filter((f) => fds.has(f.id)).flatMap((f) => f.evidence_ids)]);
  return {
    evidence: (e) => evs.has(e.id),
    event: ({ event, data }) =>
      event === "finding_added" ? fds.has(data.finding.id)
        : event === "action_proposed" ? acts.has(data.action.id)
        : event === "dns_captured" ? attacks.includes("c2_beacon")
        : true,
  };
}

function emit(c, event, data) {
  const seq = c.log.length;
  c.log.push({ event, data });
  apply(c, event, data);
  for (const res of c.subs) res.write(`event: ${event}\nid: ${seq}\ndata: ${JSON.stringify(data)}\n\n`);
}

function apply(c, event, d) {
  const det = c.detail;
  if (event === "state_changed") det.case.state = d.to_state;
  if (event === "step_started" || event === "step_finished") {
    const i = det.steps.findIndex((s) => s.id === d.step.id);
    if (i < 0) det.steps.push(d.step);
    else det.steps[i] = d.step;
  }
  if (event === "finding_added") det.findings.push(d.finding);
  if (event === "action_proposed") det.actions.push(d.action);
  if (event === "action_applied") det.actions = det.actions.map((a) => (a.id === d.action.id ? d.action : a));
  if (event === "teardown_done") det.blast_radius = d.blast_radius;
}

function openCase(instance_id, reason, { alert_id = null, filter = null } = {}) {
  const inst = INSTANCES.find((i) => i.id === instance_id);
  if (!inst) return null;
  const id = `case-${String(nextCase++).padStart(4, "0")}`;
  const base = swapInst(swapId(DETAIL, id), inst);
  const detail = {
    case: { ...base.case, instance_id, instance_label: inst.label, reason, state: "opened", alert_id,
            created_at: new Date().toISOString(), closed_at: null },
    steps: [], evidence: filter ? base.evidence.filter(filter.evidence) : base.evidence,
    findings: [], actions: [], seal: base.seal, blast_radius: null,
  };
  const c = { detail, log: [], subs: new Set(), inst };
  cases.set(id, c);
  const script = AUTO.filter((e) => !filter || filter.event(e));
  let i = 0;
  const tick = () => {
    if (i >= script.length) return;
    emit(c, script[i].event, swapInst(swapId(script[i].data, id), inst));
    i++;
    setTimeout(tick, DELAY);
  };
  tick();
  return c;
}

function approve(c, actionId, approved_by) {
  const a = c.detail.actions.find((x) => x.id === actionId);
  if (!a) return null;
  if (a.status === "applied") return a;
  const response = a.api_method
    ? { method: a.api_method, path: a.api_path, body: a.api_body, status_code: a.api_method === "PATCH" ? 202 : 204,
        response: a.api_method === "PATCH" ? { instance: { id: a.target, ...a.api_body } } : null }
    : null;
  const applied = { ...a, status: "applied", approved_by, response };
  emit(c, "action_applied", { action: applied, api: response });
  if (c.detail.case.state === "reported")
    emit(c, "state_changed", { case_id: a.case_id, from_state: "reported", to_state: "contained", detail: `${a.kind} applied` });
  return applied;
}

function close(c, id) {
  if (c.detail.case.state !== "closed") {
    emit(c, "teardown_done", swapInst(swapId(TEARDOWN, id), c.inst));
    emit(c, "state_changed", { case_id: id, from_state: c.detail.case.state, to_state: "closed", detail: "twin destroyed; snapshot kept" });
    c.detail.case.closed_at = new Date().toISOString();
  }
  return c.detail;
}

/** POST /cases/{id}/actions: the operator's own fix. The API call is built here, never taken from the client. */
let nextAction = 100;
function customAction(c, { kind, description }) { // created_by is the operator; Action records the actor ("human")
  const t = c.detail.case.instance_id;
  const api = kind === "quarantine_firewall" ? { api_method: "PATCH", api_path: `/v2/instances/${t}`, api_body: { firewall_group_id: "fw-0005" } }
    : kind === "stop_instance" ? { api_method: "POST", api_path: `/v2/instances/${t}/halt`, api_body: null }
    : { api_method: null, api_path: null, api_body: null };
  const action = { id: `act-${nextAction++}`, case_id: c.detail.case.id, kind, target: t, ...api, description, status: "proposed",
    recommended: false, created_by: "human", approved_by: null, response: null };
  emit(c, "action_proposed", { action });
  return action;
}

function infect(attacks) {
  const n = nextDemo++;
  const inst = { ...INSTANCES[0], id: `inst-demo-${String(n).padStart(4, "0")}`, label: `demo-shop-${n}`, main_ip: `45.77.20.${n % 250}` };
  INSTANCES.push(inst);
  enroll(inst.id);
  Object.assign(sensors.get(inst.id), { last_seen: new Date().toISOString(), healthy: true }); // its sensor has reported
  let alert = null;
  if (attacks.length) {
    const [signal, what] = ATTACK_SIGNAL[attacks[0]];
    const more = attacks.length > 1 ? ` (+${attacks.length - 1} more)` : "";
    alert = { id: `al-${String(nextAlert++).padStart(4, "0")}`, instance_id: inst.id, signal, source: "sensor",
      summary: signal === "new_outbound" ? `New outbound destination ${what} not in baseline${more}` : `${what} changed vs baseline${more}`,
      detail: Object.fromEntries(attacks.map((a) => [ATTACK_SIGNAL[a][1], ATTACK_SIGNAL[a][0]])),
      received_at: new Date().toISOString(), case_id: null };
    alerts.unshift(alert);
  }
  const reason = alert ? alert.summary : "Clean control: no attacks planted.";
  const c = openCase(inst.id, reason, { alert_id: alert?.id ?? null, filter: attackFilter(attacks) });
  if (alert) alert.case_id = c.detail.case.id;
  return { instance_id: inst.id, alert_id: alert?.id ?? null, case_id: c.detail.case.id };
}

const PASSWORD = process.env.MOCK_PASSWORD ?? "";

const json = (res, code, body) => {
  res.writeHead(code, { "content-type": "application/json" });
  res.end(JSON.stringify(body));
};
const body = (req) => new Promise((r) => { let s = ""; req.on("data", (d) => (s += d)); req.on("end", () => r(s ? JSON.parse(s) : {})); });

createServer(async (req, res) => {
  const url = new URL(req.url, "http://x");
  const p = url.pathname.split("/").filter(Boolean);
  const c = p[0] === "cases" && p[1] ? cases.get(p[1]) : null;
  try {
    // Operator session, as the backend does it (to-frontend.md 20:20): cookie bd_session or X-Human-Session.
    // MOCK_PASSWORD set: real-mode gate (operator password required), else fake mode.
    if (req.method === "GET" && url.pathname === "/auth/config") return json(res, 200, { password_required: !!PASSWORD });
    if (req.method === "POST" && url.pathname === "/auth/session") {
      const { operator, password } = await body(req);
      if (!operator?.trim()) return json(res, 422, { detail: "operator required" });
      if (PASSWORD && password !== PASSWORD) return json(res, 401, { detail: "wrong operator password" });
      const token = `${operator}.${Date.now()}.${Math.random().toString(16).slice(2)}`;
      sessions.add(token);
      res.setHeader("set-cookie", `bd_session=${token}; Path=/; HttpOnly; SameSite=Lax`);
      return json(res, 200, { operator, session_token: token });
    }
    // Real mode turns the demo endpoint off (backend: 404); MOCK_FAKE_CASE_OFF=1 reproduces that.
    if ((url.pathname === "/dev/fake-case" || url.pathname === "/dev/infect") && process.env.MOCK_FAKE_CASE_OFF === "1")
      return json(res, 404, { detail: "Not Found" });
    const cookie = /(?:^|;\s*)bd_session=([^;]+)/.exec(req.headers.cookie ?? "")?.[1];
    if (!sessions.has(cookie) && !sessions.has(req.headers["x-human-session"]))
      return json(res, 401, { detail: "operator session required" });
    if (req.method === "GET" && url.pathname === "/instances") return json(res, 200, INSTANCES);
    if (req.method === "GET" && url.pathname === "/sensors") return json(res, 200, [...sensors.values()]);
    if (req.method === "POST" && url.pathname === "/sensors") {
      const { instance_id } = await body(req);
      if (!INSTANCES.some((i) => i.id === instance_id)) return json(res, 404, { detail: "no such instance" });
      return json(res, 200, enroll(instance_id));
    }
    if (req.method === "GET" && url.pathname === "/alerts") return json(res, 200, alerts);
    if (req.method === "POST" && url.pathname === "/dev/infect") {
      const { attacks = [] } = await body(req);
      if (!Array.isArray(attacks) || attacks.length > 5 || attacks.some((a) => !ATTACK_FINDINGS[a]))
        return json(res, 422, { detail: "attacks must be a list of Attack values" });
      return json(res, 200, infect([...new Set(attacks)]));
    }
    if (req.method === "POST" && (url.pathname === "/cases" || url.pathname === "/dev/fake-case")) {
      const b = await body(req);
      const instance_id = b.instance_id ?? "inst-shop-prod";
      const reason = b.reason ?? "CPU at 100% overnight, unknown process.";
      if (!reason.trim()) return json(res, 422, { detail: "reason required" });
      const made = openCase(instance_id, reason);
      return made ? json(res, 200, made.detail.case) : json(res, 404, { detail: "no such instance" });
    }
    if (p[0] === "cases" && !c) return json(res, 404, { detail: "no such case" });
    if (req.method === "GET" && p.length === 2) return json(res, 200, c.detail);
    if (req.method === "GET" && p[2] === "stream") {
      res.writeHead(200, { "content-type": "text/event-stream", "cache-control": "no-cache", connection: "keep-alive" });
      const from = Number(req.headers["last-event-id"] ?? -1) + 1;
      c.log.slice(from).forEach((e, k) => res.write(`event: ${e.event}\nid: ${from + k}\ndata: ${JSON.stringify(e.data)}\n\n`));
      c.subs.add(res);
      req.on("close", () => c.subs.delete(res));
      return;
    }
    if (req.method === "POST" && p[2] === "actions" && p.length === 3) {
      const b = await body(req);
      const KINDS = ["quarantine_firewall", "revoke_ssh_key", "stop_instance", "rotate_secrets", "manual_plan"];
      if (!KINDS.includes(b.kind) || !b.description?.trim() || !b.created_by?.trim())
        return json(res, 422, { detail: "kind, description and created_by required" });
      if (c.detail.case.state !== "reported") return json(res, 409, { detail: `case is ${c.detail.case.state}` });
      return json(res, 200, customAction(c, b));
    }
    if (req.method === "POST" && p[2] === "actions" && p[4] === "approve") {
      const b = await body(req);
      if (!b.approved_by) return json(res, 422, { detail: "approved_by required" });
      const a = approve(c, p[3], b.approved_by);
      return a ? json(res, 200, a) : json(res, 404, { detail: "no such action" });
    }
    if (req.method === "POST" && p[2] === "close") return json(res, 200, close(c, p[1]));
    if (req.method === "GET" && p[2] === "bundle") {
      const d = c.detail;
      const zip = zipSync({
        "case.json": strToU8(JSON.stringify(d, null, 2)),
        "case_log.jsonl": strToU8(c.log.map((e, seq) => JSON.stringify({ seq, ...e })).join("\n")),
        "hashes.txt": strToU8(d.evidence.map((e) => `${e.sha256}  ${e.path}`).join("\n")),
        "snapshot.txt": strToU8(`snapshot_id=${d.case.snapshot_id}\n`),
      });
      res.writeHead(200, { "content-type": "application/zip", "content-disposition": `attachment; filename="${p[1]}-evidence.zip"` });
      return res.end(Buffer.from(zip));
    }
    json(res, 404, { detail: "not found" });
  } catch (e) {
    json(res, 500, { detail: String(e) });
  }
}).listen(PORT, () => console.log(`mock control plane on :${PORT} (delay ${DELAY}ms)`));
