import { useEffect, useState } from 'react'
import { api } from '../api/client'
import type { Action, Alert, VultrInstance } from '../api/types'
import type { LiveCase } from './useCase'

/** Left column: the real server. Nothing here moves unless a human approved it. */
export function Production({ live, server }: { live: LiveCase; server: VultrInstance | null }) {
  const c = live.detail?.case
  const applied = live.actions.filter((a) => a.status === 'applied')
  const quarantine = applied.find((a) => a.kind === 'quarantine_firewall')
  const halted = applied.some((a) => a.kind === 'stop_instance')
  const newGroup = (quarantine?.api_body as { firewall_group_id?: string } | null)?.firewall_group_id

  return (
    <section aria-labelledby="col-prod" className="flex flex-col gap-4" data-testid="col-production">
      <header className="flex items-baseline justify-between gap-3">
        <h2 id="col-prod" className="label">Production</h2>
        <span className="font-mono text-xs text-muted">real server</span>
      </header>

      <article className="border border-line bg-panel rounded-xs">
        <div className="p-5">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <p className="text-xl font-semibold tracking-[-0.01em] truncate">{c?.instance_label ?? server?.label ?? '...'}</p>
              <p className="font-mono text-xs text-muted mt-0.5 truncate">{c?.instance_id ?? ''}</p>
            </div>
            <LockBadge applied={applied} />
          </div>

          <dl className="mt-5 grid grid-cols-[auto_1fr] gap-x-4 gap-y-2 text-sm">
            <dt className="text-muted">Public IP</dt>
            <dd className="font-mono">{server?.main_ip ?? '...'}</dd>
            <dt className="text-muted">Region</dt>
            <dd className="font-mono">{server?.region ?? '...'}</dd>
            <dt className="text-muted">Plan</dt>
            <dd className="font-mono">{server?.plan || 'n/a'}</dd>
            <dt className="text-muted">Power</dt>
            <dd className={halted ? 'font-mono text-agent' : 'font-mono'}>{halted ? 'halted (approved)' : server?.power_status ?? '...'}</dd>
          </dl>
        </div>

        <div className="border-t border-line p-5">
          <p className="label">Firewall group</p>
          {quarantine ? (
            <p className="mt-2 font-mono text-sm" data-testid="prod-firewall">
              <s className="text-muted">{server?.firewall_group_id || 'none'}</s>
              <span aria-hidden="true" className="text-muted"> → </span>
              <span className="sr-only"> changed to </span>
              <span className="text-agent">{newGroup}</span>
            </p>
          ) : (
            <p className="mt-2 font-mono text-sm" data-testid="prod-firewall">{server?.firewall_group_id || 'none'}</p>
          )}
          <p className="mt-1 text-xs text-muted">
            {quarantine ? 'Quarantine applied after your approval.' : 'Unchanged. Serving traffic as before.'}
          </p>
        </div>
      </article>

      {c?.alert_id && <AlertQuote alertId={c.alert_id} />}

      {c?.reason && !c.alert_id && (
        <figure className="border-l border-line pl-4">
          <blockquote className="text-sm">&ldquo;{c.reason}&rdquo;</blockquote>
          <figcaption className="mt-1 text-xs text-muted">Reason given when the case was opened</figcaption>
        </figure>
      )}
    </section>
  )
}

function LockBadge({ applied }: { applied: Action[] }) {
  if (applied.length === 0)
    return (
      <span className="shrink-0 inline-flex items-center gap-1.5 border border-line rounded-xs px-2 py-1 font-mono text-xs" data-testid="lock-badge">
        <svg width="10" height="12" viewBox="0 0 10 12" aria-hidden="true">
          <rect x="0.75" y="5" width="8.5" height="6.25" rx="1" fill="none" stroke="currentColor" strokeWidth="1.5" />
          <path d="M2.5 5V3.5a2.5 2.5 0 0 1 5 0V5" fill="none" stroke="currentColor" strokeWidth="1.5" />
        </svg>
        untouched
      </span>
    )
  return (
    <span className="shrink-0 inline-flex items-center gap-1.5 border border-agent text-agent rounded-xs px-2 py-1 font-mono text-xs" data-testid="lock-badge">
      {applied.length} approved {applied.length === 1 ? 'change' : 'changes'}
    </span>
  )
}

const SIGNAL: Record<string, string> = {
  file_changed: 'file changed', new_outbound: 'new outbound', heartbeat_lost: 'heartbeat lost', external: 'external alert',
}

/** The alert that opened this case, quoted. Alert text is untrusted data: rendered as text, never as HTML. */
function AlertQuote({ alertId }: { alertId: string }) {
  const [alert, setAlert] = useState<Alert | null>(null)
  useEffect(() => {
    api.alerts().then((xs) => setAlert(xs.find((a) => a.id === alertId) ?? null)).catch(() => {})
  }, [alertId])
  return (
    <figure className="latch border border-finding/60 bg-finding/5 p-4" data-testid="case-alert">
      <p className="label"><span className="text-finding">Sensor alert</span> opened this case</p>
      <blockquote className="mt-2 text-sm">&ldquo;{alert?.summary ?? '...'}&rdquo;</blockquote>
      <figcaption className="mt-1 font-mono text-xs text-muted">
        {alert ? `${SIGNAL[alert.signal] ?? alert.signal} · ${alert.source} · ${alert.id}` : alertId}
      </figcaption>
    </figure>
  )
}
