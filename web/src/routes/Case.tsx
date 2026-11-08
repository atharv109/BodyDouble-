import { useEffect, useState } from 'react'
import { Link, useLocation, useParams } from 'react-router'
import { api } from '../api/client'
import type { VultrInstance } from '../api/types'
import { ApproveDrawer } from '../case/Approve'
import { AnalystConsole } from '../case/AnalystConsole'
import { Production } from '../case/Production'
import { InvestigationLog, StatusBand, TaskRail } from '../case/Terminal'
import { useCase } from '../case/useCase'
import { useTitle } from '../ui/useTitle'

export function CaseScreen() {
  const { id } = useParams()
  const location = useLocation()
  const openedFromDemo = (location.state as { from?: string } | null)?.from === 'infect'
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
    <div className="wrap pt-6 pb-12">
      <section aria-label={`Case ${id ?? ''}`} className="grid gap-4" data-testid="col-twin">
        <StatusBand live={live} caseId={id} actions={<>
          {canClose && <Link to={`/cases/${id}/evidence`} className="btn">Close and evidence</Link>}
          <button type="button" className="btn btn-agent" disabled={!proposed} data-testid="open-approve"
            onClick={() => setDrawer(true)}>
            {proposed ? `Review ${proposed} proposed ${proposed === 1 ? 'action' : 'actions'}` : 'No actions proposed yet'}
          </button>
        </>} />

        {openedFromDemo && <p className="case-handoff" role="status"><strong>Demo sensor opened this real case record.</strong> You are now in the live investigation timeline for case <span className="font-mono">{id}</span>.</p>}

        {live.error && !live.detail && (
          <div role="alert" className="border border-line bg-panel p-4 text-sm">
            <p className="font-medium">This case could not be loaded.</p>
            <p className="mt-1 font-mono text-muted break-all">{live.error}</p>
          </div>
        )}

        <div className={`case-grid ${ready ? '' : 'invisible'}`} aria-busy={!ready}>
          <InvestigationLog live={live} />
          {/* Production sits at the top of the rail: the original never leaves the room. */}
          <div className="case-prod"><Production live={live} server={server} /></div>
          <aside className="case-rail" aria-label="Case status"><TaskRail live={live} /></aside>
        </div>
        {id && <AnalystConsole caseId={id} state={live.state} />}
      </section>

      {id && <ApproveDrawer live={live} caseId={id} open={drawer} onClose={() => setDrawer(false)} />}
    </div>
  )
}
