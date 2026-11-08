import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router'
import { api } from '../api/client'
import type { VultrInstance } from '../api/types'
import { EVENT_NAMES } from '../api/types'
import { ApproveDrawer } from '../case/Approve'
import { Production } from '../case/Production'
import { Terminal } from '../case/Terminal'
import { useCase } from '../case/useCase'
import { useTitle } from '../ui/useTitle'

export function CaseScreen() {
  const { id } = useParams()
  const live = useCase(id)
  const c = live.detail?.case
  const label = c?.instance_label ?? ''
  useTitle(label ? `${label}, ${id}` : `Case ${id}`)

  const [server, setServer] = useState<VultrInstance | null>(null)
  useEffect(() => {
    if (!c?.instance_id) return
    api.instances().then((xs) => setServer(xs.find((x) => x.id === c.instance_id) ?? null)).catch(() => {})
  }, [c?.instance_id, live.seen.action_applied])

  // On connect the server replays the whole case in a burst. Keep the columns invisible until that burst
  // goes quiet (or 1.5 s pass) so the replay doesn't register as layout shift; later events latch in live.
  const events = Object.values(live.seen).reduce((a, b) => a + (b ?? 0), 0)
  const [ready, setReady] = useState(false)
  useEffect(() => { setReady(false) }, [id])
  useEffect(() => {
    if (ready || !live.detail) return
    const t = setTimeout(() => setReady(true), live.connected ? 200 : 1500)
    return () => clearTimeout(t)
  }, [ready, live.detail, live.connected, events])

  const [drawer, setDrawer] = useState(false)
  const proposed = live.actions.filter((a) => a.status === 'proposed').length
  const canClose = live.state === 'reported' || live.state === 'contained' || live.state === 'closed'

  return (
    <div className="mx-auto max-w-[1600px] w-full px-4 md:px-6 pt-8 pb-16">
      <header className="flex flex-wrap items-end gap-x-8 gap-y-4 pb-6 border-b border-line">
        <div className="min-w-0">
          <p className="label">Case <span className="font-mono normal-case tracking-normal">{id}</span></p>
          <h1 className="mt-1 text-[2.25rem] md:text-[3.5rem] leading-[1] font-semibold tracking-[-0.035em] -ml-[0.04em]">
            {label || '...'} <span className="text-muted font-normal">and its twin</span>
          </h1>
        </div>
        <p className="font-mono text-xs text-muted flex items-center gap-2" aria-live="off" data-testid="stream-status">
          <span aria-hidden="true" className={`size-1.5 rounded-full ${live.connected ? 'bg-ink' : 'bg-muted/50'}`} />
          {live.connected ? 'live' : live.state === 'closed' ? 'closed' : 'reconnecting'} · {events} events
        </p>
        {/* Phone: primary first and full width (column-reverse puts the approve button on top). */}
        <div className="w-full sm:w-auto sm:ml-auto flex flex-col-reverse sm:flex-row flex-wrap gap-3 [&>*]:justify-center">
          {canClose && (
            <Link to={`/cases/${id}/evidence`} className="btn">Close and evidence</Link>
          )}
          <button type="button" className="btn btn-agent" disabled={!proposed} data-testid="open-approve"
            onClick={() => setDrawer(true)}>
            {proposed ? `Review ${proposed} proposed ${proposed === 1 ? 'action' : 'actions'}` : 'No actions proposed yet'}
          </button>
        </div>
      </header>

      {live.error && !live.detail && (
        <div role="alert" className="mt-6 border border-line bg-panel p-4 text-sm">
          <p className="font-medium">This case could not be loaded.</p>
          <p className="mt-1 font-mono text-muted break-all">{live.error}</p>
        </div>
      )}

      <div className={`mt-8 grid grid-cols-1 lg:grid-cols-12 gap-10 lg:gap-0 ${ready ? '' : 'invisible'}`} aria-busy={!ready}>
        {/* Production stays pinned beside the twin while you scroll: the original never leaves the room. */}
        <div className="order-1 lg:col-span-3 lg:pr-6 lg:sticky lg:top-6 lg:self-start"><Production live={live} server={server} /></div>
        {/* The twin is a terminal: commands, AI reasoning, sandbox, seal + log. */}
        <div className="order-2 lg:col-span-9 min-w-0"><Terminal live={live} /></div>
      </div>

      {id && <ApproveDrawer live={live} caseId={id} open={drawer} onClose={() => setDrawer(false)} />}

      <footer className="mt-12 pt-4 border-t border-line">
        <h2 className="label mb-2">Event log, from the case stream</h2>
        <ul className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-xs text-muted" data-testid="event-ledger">
          {EVENT_NAMES.map((n) => (
            <li key={n} data-event={n} data-count={live.seen[n] ?? 0} className={live.seen[n] ? 'text-ink' : 'text-muted'}>
              {n} <span className={live.seen[n] ? 'text-agent' : 'text-muted'}>{live.seen[n] ?? 0}</span>
            </li>
          ))}
        </ul>
      </footer>
    </div>
  )
}
