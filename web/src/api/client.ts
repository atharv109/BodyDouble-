import type { Action, Case, CaseDetail, VultrInstance } from './types'

export const API = '/api'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

async function call<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(API + path, {
    method,
    headers: body === undefined ? undefined : { 'content-type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  if (!res.ok) {
    let msg = `${method} ${path} -> ${res.status}`
    try { const j = await res.json(); if (j?.detail) msg += `: ${typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail)}` } catch { /* not json */ }
    throw new ApiError(res.status, msg)
  }
  return res.json() as Promise<T>
}

export const api = {
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
