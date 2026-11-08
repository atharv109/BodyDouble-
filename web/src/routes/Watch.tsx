import { useEffect, useId, useRef, useState } from 'react'
import { Link } from 'react-router'
import { api } from '../api/client'
import type { Alert, SensorEnrollResponse, SensorStatus, VultrInstance } from '../api/types'

/** Sensor column of the servers table: watched (healthy or silent) or not, and the watch action. */
export function SensorCell({ server, status, onWatch }: { server: VultrInstance; status?: SensorStatus; onWatch: () => void }) {
  if (status) {
    const waiting = !status.last_seen // enrolled, but the sensor has not reported yet (not installed, or just now)
    return (
      <span className="inline-flex items-center gap-2 text-sm" data-testid={`sensor-${server.id}`} data-healthy={status.healthy}>
        <span aria-hidden="true" className={`size-1.5 rounded-full ${status.healthy ? 'bg-agent' : waiting ? 'bg-muted' : 'bg-finding'}`} />
        {status.healthy ? 'watched' : waiting ? 'watched, waiting for first report' : 'watched, silent'}
      </span>
    )
  }
  return (
    <button type="button" className="btn" onClick={onWatch} aria-label={`Watch ${server.label}`} data-testid={`watch-${server.id}`}>
      Watch
    </button>
  )
}

/**
 * POST /sensors for one server and show what to run there. The token lives only inside these two
 * commands and only while the dialog is open: closing it drops the response for good.
 */
export function WatchDialog({ server, onClose }: { server: VultrInstance | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const id = useId()
  const [res, setRes] = useState<SensorEnrollResponse | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (server && !d.open) {
      setRes(null); setError(null); d.showModal()
      api.enroll(server.id).then(setRes).catch((e) => setError(String(e.message ?? e)))
    }
    if (!server && d.open) d.close()
  }, [server])

  return (
    <dialog
      ref={ref}
      onClose={() => { setRes(null); onClose() }}
      aria-labelledby={`${id}-t`}
      data-testid="watch-dialog"
      className="m-auto w-[min(720px,calc(100vw-32px))] bg-panel text-ink border border-line rounded-xs p-0 backdrop:bg-black/70"
    >
      {server && (
        <div className="p-6 md:p-8">
          <p className="label">Put a sensor on it</p>
          <h2 id={`${id}-t`} className="mt-2 text-2xl font-semibold tracking-[-0.02em]">Watch {server.label}</h2>
          <p className="mt-2 text-sm text-muted max-w-[60ch]">
            The sensor checks cron, root SSH keys, system binaries and outbound connections every 30 s. When one changes it
            reports here and a case opens on its own. It opens no port and runs nothing it is sent.
          </p>

          {error && <p role="alert" className="mt-6 text-sm font-mono border border-line p-3 break-all">{error}</p>}
          {!res && !error && <p className="mt-6 text-sm text-muted">Issuing a token...</p>}
          {res && (
            <>
              <p className="mt-6 border border-agent/60 bg-agent/5 p-3 text-sm" data-testid="token-once">
                The token is inside both commands and is shown <strong>once</strong>. Copy one now; closing this hides it for good.
              </p>
              <Command label="On the running server, as root" text={res.install_command} testid="install-command" />
              <details className="fold mt-5 border-t border-line pt-3">
                <summary className="min-h-9 font-mono text-xs text-muted"><span aria-hidden="true" className="chev mr-2">▸</span>New server: Vultr startup script</summary>
                <Command label="Vultr startup script" text={res.startup_script} testid="startup-script" />
              </details>
            </>
          )}

          <div className="mt-8 flex justify-end">
            <button type="button" className="btn btn-primary" onClick={() => ref.current?.close()}>Done</button>
          </div>
        </div>
      )}
    </dialog>
  )
}

function Command({ label, text, testid }: { label: string; text: string; testid: string }) {
  const [copied, setCopied] = useState<'idle' | 'ok' | 'fail'>('idle')
  async function copy() {
    try { await navigator.clipboard.writeText(text); setCopied('ok') } catch { setCopied('fail') }
  }
  return (
    <div className="mt-5">
      <div className="flex items-baseline justify-between gap-3">
        <p className="label">{label}</p>
        <button type="button" className="btn h-9 min-h-0 px-3 text-sm" onClick={copy} data-testid={`copy-${testid}`}>
          {copied === 'ok' ? 'Copied' : copied === 'fail' ? 'Select and copy' : 'Copy'}
        </button>
      </div>
      <pre className="mt-2 bg-ground border border-line rounded-xs p-3 font-mono text-xs whitespace-pre-wrap break-all select-all" data-testid={testid}>{text}</pre>
    </div>
  )
}

const SIGNAL: Record<string, string> = {
  file_changed: 'file changed', new_outbound: 'new outbound', heartbeat_lost: 'heartbeat lost', external: 'external',
}
const time = (iso: string) => new Date(iso).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })

/** GET /alerts, newest first. Alert text is untrusted data from a server that may be compromised: text only. */
export function AlertsInbox({ alerts, labels }: { alerts: Alert[] | null; labels: Record<string, string> }) {
  return (
    <section aria-labelledby="alerts-t" className="mt-12" data-testid="alerts">
      <div className="flex items-baseline justify-between gap-4 border-b border-line pb-3">
        <h2 id="alerts-t" className="label">Alerts</h2>
        <span className="font-mono text-xs text-muted">{alerts ? alerts.length : '...'}</span>
      </div>
      {alerts?.length === 0 && <p className="py-5 text-sm text-muted">No alerts yet. Watched servers report here, and each alert opens a case.</p>}
      <ul>
        {alerts?.map((a) => (
          <li key={a.id} className="grid grid-cols-1 sm:grid-cols-[9rem_1fr_auto] gap-x-6 gap-y-1 py-4 border-b border-line" data-testid={`alert-${a.id}`}>
            <p className="font-mono text-xs text-muted sm:pt-0.5">
              <span className="text-finding">{SIGNAL[a.signal] ?? a.signal}</span><br className="hidden sm:inline" />
              <span className="sm:hidden"> · </span>{time(a.received_at)}
            </p>
            <div className="min-w-0">
              <p className="font-medium">{labels[a.instance_id] ?? a.instance_id} <span className="font-mono text-xs text-muted">{a.source}</span></p>
              <blockquote className="mt-1 text-sm text-muted wrap-anywhere">&ldquo;{a.summary}&rdquo;</blockquote>
            </div>
            {a.case_id
              ? <Link to={`/cases/${a.case_id}`} className="btn self-start" aria-label={`Open case ${a.case_id}`}>Case {a.case_id}</Link>
              : <span className="font-mono text-xs text-muted self-start">no case</span>}
          </li>
        ))}
      </ul>
    </section>
  )
}
