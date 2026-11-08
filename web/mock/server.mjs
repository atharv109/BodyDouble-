// Mock control plane: replays contracts/fixtures when the real backend on :8000 is down.
// Implements the PRD HTTP API + POST /dev/fake-case. Usage: node mock/server.mjs [port]
// MOCK_DELAY=ms between replayed events (default 350).
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

function openCase(instance_id, reason) {
  const inst = INSTANCES.find((i) => i.id === instance_id);
  if (!inst) return null;
  const id = `case-${String(nextCase++).padStart(4, "0")}`;
  const base = swapId(DETAIL, id);
  const detail = {
    case: { ...base.case, instance_id, instance_label: inst.label, reason, state: "opened",
            created_at: new Date().toISOString(), closed_at: null },
    steps: [], evidence: base.evidence, findings: [], actions: [], seal: base.seal, blast_radius: null,
  };
  const c = { detail, log: [], subs: new Set() };
  cases.set(id, c);
  let i = 0;
  const tick = () => {
    if (i >= AUTO.length) return;
    emit(c, AUTO[i].event, swapId(AUTO[i].data, id));
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
    emit(c, "teardown_done", swapId(TEARDOWN, id));
    emit(c, "state_changed", { case_id: id, from_state: c.detail.case.state, to_state: "closed", detail: "twin destroyed; snapshot kept" });
    c.detail.case.closed_at = new Date().toISOString();
  }
  return c.detail;
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
    const cookie = /(?:^|;\s*)bd_session=([^;]+)/.exec(req.headers.cookie ?? "")?.[1];
    if (!sessions.has(cookie) && !sessions.has(req.headers["x-human-session"]))
      return json(res, 401, { detail: "operator session required" });
    if (req.method === "GET" && url.pathname === "/instances") return json(res, 200, INSTANCES);
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
