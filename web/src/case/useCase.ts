import { useEffect, useReducer, useRef } from 'react'
import { api } from '../api/client'
import type {
  Action, ApiResponse, CaseDetail, CaseState, DnsCaptured, EventName, Evidence, Finding, SealCheck, StateChanged,
  Step, TeardownDone,
} from '../api/types'
import { EVENT_NAMES } from '../api/types'

export type Transition = { from: CaseState | null; to: CaseState; detail: string }

export type LiveCase = {
  connected: boolean
  error: string | null
  detail: CaseDetail | null // GET /cases/{id}: case metadata + evidence (the stream doesn't carry Evidence)
  state: CaseState | null
  transitions: Transition[]
  seals: Record<string, SealCheck>
  steps: Step[]
  dns: DnsCaptured[]
  findings: Finding[]
  actions: Action[]
  responses: Record<string, ApiResponse | null> // action_id -> api response, from action_applied
  teardown: TeardownDone | null
  seen: Partial<Record<EventName, number>> // count per event type, for the UI and tests
  lastSeq: number
}

const initial: LiveCase = {
  connected: false, error: null, detail: null, state: null, transitions: [], seals: {}, steps: [], dns: [],
  findings: [], actions: [], responses: {}, teardown: null, seen: {}, lastSeq: -1,
}

type Msg =
  | { t: 'event'; name: EventName; seq: number; data: any }
  | { t: 'detail'; detail: CaseDetail }
  | { t: 'conn'; connected: boolean; error?: string | null }
  | { t: 'reset' }

const upsert = <T extends { id: string }>(xs: T[], x: T) => {
  const i = xs.findIndex((y) => y.id === x.id)
  return i < 0 ? [...xs, x] : xs.map((y, k) => (k === i ? x : y))
}

function reduce(s: LiveCase, m: Msg): LiveCase {
  switch (m.t) {
    case 'reset': return initial
    case 'conn': return { ...s, connected: m.connected, error: m.error ?? (m.connected ? null : s.error) }
    case 'detail': return { ...s, detail: m.detail, state: s.state ?? m.detail.case.state ?? null }
    case 'event': {
      if (m.seq <= s.lastSeq) return s // replay after reconnect
      const n = { ...s, lastSeq: m.seq, seen: { ...s.seen, [m.name]: (s.seen[m.name] ?? 0) + 1 } }
      const d = m.data
      switch (m.name) {
        case 'state_changed': {
          const e = d as StateChanged
          return { ...n, state: e.to_state, transitions: [...s.transitions, { from: e.from_state ?? null, to: e.to_state, detail: e.detail ?? '' }] }
        }
        case 'seal_check': return { ...n, seals: { ...s.seals, [d.check]: d } }
        case 'step_started':
        case 'step_finished': return { ...n, steps: upsert(s.steps, d.step as Step) }
        case 'dns_captured': return { ...n, dns: [...s.dns, d] }
        case 'finding_added': return { ...n, findings: upsert(s.findings, d.finding as Finding) }
        case 'action_proposed': return { ...n, actions: upsert(s.actions, d.action as Action) }
        case 'action_applied':
          return { ...n, actions: upsert(s.actions, d.action as Action), responses: { ...s.responses, [d.action.id]: d.api ?? null } }
        case 'teardown_done': return { ...n, teardown: d }
      }
      return n
    }
  }
}

/** Live view of one case: GET /cases/{id} for metadata + evidence, SSE for everything that happens. */
export function useCase(id: string | undefined) {
  const [s, dispatch] = useReducer(reduce, initial)
  const refetch = useRef<() => void>(() => {})

  useEffect(() => {
    if (!id) return
    dispatch({ t: 'reset' })
    let alive = true
    let pending: ReturnType<typeof setTimeout> | null = null
    const load = () => api.caseDetail(id).then((d) => alive && dispatch({ t: 'detail', detail: d }))
      .catch((e) => alive && dispatch({ t: 'conn', connected: false, error: String(e.message ?? e) }))
    // Evidence only arrives via GET; refetch (debounced) when the stream says something new was hashed.
    refetch.current = () => { if (pending) clearTimeout(pending); pending = setTimeout(load, 150) }
    load()

    const es = new EventSource(api.streamUrl(id))
    es.onopen = () => dispatch({ t: 'conn', connected: true })
    es.onerror = () => dispatch({ t: 'conn', connected: false, error: es.readyState === EventSource.CLOSED ? 'stream closed' : null })
    for (const name of EVENT_NAMES) {
      es.addEventListener(name, (ev) => {
        const me = ev as MessageEvent
        dispatch({ t: 'event', name, seq: Number(me.lastEventId), data: JSON.parse(me.data) })
        if (name === 'finding_added' || name === 'dns_captured' || name === 'teardown_done' || name === 'state_changed')
          refetch.current()
      })
    }
    return () => { alive = false; es.close(); if (pending) clearTimeout(pending) }
  }, [id])

  return s
}

export function evidenceIndex(detail: CaseDetail | null): Record<string, Evidence> {
  return Object.fromEntries((detail?.evidence ?? []).map((e) => [e.id, e]))
}
