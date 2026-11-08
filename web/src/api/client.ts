import type { Action, Case, CaseDetail, VultrInstance } from './types'

export const API = '/api'
const OPERATOR_KEY = 'bd.operator'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

// The operator name is a per-browser convenience; the session itself is the HttpOnly bd_session cookie
// (sent automatically on fetch and EventSource through the same-origin /api proxy).
export function getOperator(): string | null {
  try { return localStorage.getItem(OPERATOR_KEY) } catch { return null }
}
function setOperator(name: string | null) {
  try { if (name) localStorage.setItem(OPERATOR_KEY, name); else localStorage.removeItem(OPERATOR_KEY) } catch { /* private mode */ }
}

export const AUTH_REQUIRED = 'bd:auth-required'

// Real mode can require an operator password (GET /auth/config). The password is never stored, so in
// that mode an expired session goes back to the gate instead of being re-minted silently.
let passwordRequired = false
async function authConfig(): Promise<{ password_required: boolean }> {
  try {
    const res = await fetch(`${API}/auth/config`)
    passwordRequired = res.ok ? !!(await res.json()).password_required : false
  } catch { passwordRequired = false }
  return { password_required: passwordRequired }
}

async function startSession(operator: string, password?: string) {
  const res = await fetch(`${API}/auth/session`, {
    method: 'POST', headers: { 'content-type': 'application/json' },
    body: JSON.stringify(password === undefined ? { operator } : { operator, password }),
  })
  if (!res.ok) throw new ApiError(res.status, `POST /auth/session -> ${res.status}`)
  setOperator(operator)
}

async function call<T>(method: string, path: string, body?: unknown, retried = false): Promise<T> {
  const res = await fetch(API + path, {
    method,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (res.status === 401) {
    // Session expired or backend restarted: re-mint once from the stored operator, else ask who is operating.
    const op = getOperator()
    if (op && !retried && !passwordRequired) { await startSession(op); return call<T>(method, path, body, true) }
    window.dispatchEvent(new Event(AUTH_REQUIRED))
  }
  if (!res.ok) {
    let msg = `${method} ${path} -> ${res.status}`
    try { const j = await res.json(); if (j?.detail) msg += `: ${typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)}` } catch { /* not json */ }
    throw new ApiError(res.status, msg)
  }
  return res.json() as Promise<T>
}

export const api = {
  authConfig,
  session: startSession,
  signOut: () => setOperator(null),
  instances: () => call<VultrInstance[]>('GET', '/instances'),
  openCase: (instance_id: string, reason: string) => call<Case>('POST', '/cases', { instance_id, reason }),
  fakeCase: () => call<Case>('POST', '/dev/fake-case', {}),
  caseDetail: (id: string) => call<CaseDetail>('GET', `/cases/${id}`),
  approve: (id: string, actionId: string, approved_by: string) =>
    call<Action>('POST', `/cases/${id}/actions/${actionId}/approve`, { approved_by }),
  close: (id: string) => call<CaseDetail>('POST', `/cases/${id}/close`),
  streamUrl: (id: string) => `${API}/cases/${id}/stream`,
  bundleUrl: (id: string) => `${API}/cases/${id}/bundle`,
}
