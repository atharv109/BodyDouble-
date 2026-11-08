import { useEffect, useId, useRef, useState } from 'react'
import { useNavigate } from 'react-router'
import { api } from '../api/client'
import type { VultrInstance } from '../api/types'
import { useTitle } from '../ui/useTitle'

const REGIONS: Record<string, string> = {
  ewr: 'New Jersey', ord: 'Chicago', dfw: 'Dallas', lax: 'Los Angeles', sjc: 'Silicon Valley', atl: 'Atlanta',
  mia: 'Miami', sea: 'Seattle', ams: 'Amsterdam', fra: 'Frankfurt', lhr: 'London', cdg: 'Paris', nrt: 'Tokyo', sgp: 'Singapore',
}

export function Servers() {
  useTitle('Servers')
  const [list, setList] = useState<VultrInstance[] | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [target, setTarget] = useState<VultrInstance | null>(null)

  useEffect(() => {
    api.instances().then(setList).catch((e) => setError(String(e.message ?? e)))
  }, [])

  return (
    <section className="mx-auto max-w-[1600px] w-full px-4 md:px-6 pt-12 md:pt-16 pb-16 grid grid-cols-1 lg:grid-cols-12 gap-x-6 gap-y-10">
      <h1 className="lg:col-span-12 text-[2.75rem] md:text-[4rem] xl:text-[5rem] leading-[0.95] font-semibold tracking-[-0.04em] -ml-[0.05em] max-w-[14ch] xl:max-w-none">
        Pick the server that worries you.
      </h1>
      <header className="lg:col-span-4 xl:col-span-3">
        <p className="text-muted max-w-[34ch]">
          The alert or the hunch is yours. Body Double snapshots that server and investigates an exact copy in a sealed room. The server you pick keeps running, and
          nothing is written to it until you approve a change.
        </p>
        <dl className="mt-8 grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          <dt className="label leading-[1.6]">Source</dt>
          <dd className="font-mono text-muted">GET /v2/instances</dd>
          <dt className="label leading-[1.6]">Servers</dt>
          <dd className="font-mono text-muted" data-testid="server-count">{list ? list.length : '...'}</dd>
        </dl>
      </header>

      <div className="lg:col-span-8 xl:col-span-9 lg:pt-3">
        {error && (
          <div role="alert" className="border border-line bg-panel p-4 text-sm">
            <p className="font-medium">Could not reach the control plane.</p>
            <p className="mt-1 font-mono text-muted break-all">{error}</p>
          </div>
        )}
        {!error && (
          <table className="w-full text-left border-collapse">
            <caption className="sr-only">Vultr instances on this account</caption>
            <thead>
              <tr className="border-b border-line">
                <th scope="col" className="label font-normal py-3 pr-4">Server</th>
                <th scope="col" className="label font-normal py-3 pr-4 hidden md:table-cell">Region</th>
                <th scope="col" className="label font-normal py-3 pr-4">Public IP</th>
                <th scope="col" className="label font-normal py-3 pr-4 hidden xl:table-cell">Plan</th>
                <th scope="col" className="label font-normal py-3 pr-4 hidden sm:table-cell">Status</th>
                <th scope="col" className="py-3"><span className="sr-only">Action</span></th>
              </tr>
            </thead>
            <tbody>
              {list === null && (
                <tr><td colSpan={6} className="py-6 text-muted">Listing instances...</td></tr>
              )}
              {list?.length === 0 && (
                <tr><td colSpan={6} className="py-6 text-muted">This account has no instances.</td></tr>
              )}
              {list?.map((s) => (
                <tr key={s.id} className="group border-b border-line hover:bg-panel transition-colors" data-testid={`server-${s.id}`}>
                  <td className="py-4 pr-4 align-top">
                    <div className="font-medium">{s.label}</div>
                    <div className="font-mono text-xs text-muted mt-0.5">{s.id}</div>
                    <div className="sm:hidden text-xs text-muted mt-1">{s.region} · {s.status}, {s.power_status}</div>
                  </td>
                  <td className="py-4 pr-4 align-top hidden md:table-cell">
                    <span className="font-mono text-sm">{s.region}</span>
                    <span className="text-muted text-sm"> · {REGIONS[s.region] ?? 'region'}</span>
                  </td>
                  <td className="py-4 pr-4 align-top font-mono text-sm">{s.main_ip}</td>
                  <td className="py-4 pr-4 align-top hidden xl:table-cell">
                    <div className="font-mono text-sm">{s.plan}</div>
                    <div className="text-xs text-muted mt-0.5">{s.os}</div>
                  </td>
                  <td className="py-4 pr-4 align-top hidden sm:table-cell">
                    <span className="inline-flex items-center gap-2 text-sm">
                      <span aria-hidden="true" className={`size-1.5 rounded-full ${s.status === 'active' && s.power_status === 'running' ? 'bg-ink' : 'bg-muted'}`} />
                      {s.status}{s.power_status ? `, ${s.power_status}` : ''}
                    </span>
                  </td>
                  <td className="py-3 align-top text-right">
                    <button type="button" className="btn" onClick={() => setTarget(s)} aria-label={`Investigate ${s.label}`}>
                      Investigate
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {import.meta.env.DEV && <FakeCase />}
      </div>
      <div className="lg:col-span-12"><Lifecycle /></div>

      <InvestigateDialog server={target} onClose={() => setTarget(null)} />
    </section>
  )
}

function InvestigateDialog({ server, onClose }: { server: VultrInstance | null; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const nav = useNavigate()
  const id = useId()
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (server && !d.open) { setReason(''); setError(null); setBusy(false); d.showModal() }
    if (!server && d.open) d.close()
  }, [server])

  async function submit(e: React.FormEvent) {
    e.preventDefault()
    if (!server || !reason.trim()) return
    setBusy(true)
    setError(null)
    try {
      const c = await api.openCase(server.id, reason.trim())
      ref.current?.close()
      nav(`/cases/${c.id}`)
    } catch (err) {
      setError(String((err as Error).message ?? err))
      setBusy(false)
    }
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby={`${id}-t`}
      className="m-auto w-[min(560px,calc(100vw-32px))] bg-panel text-ink border border-line rounded-xs p-0 backdrop:bg-black/70"
    >
      {server && (
        <form onSubmit={submit} className="p-6 md:p-8">
          <p className="label">Open a case</p>
          <h2 id={`${id}-t`} className="mt-2 text-2xl font-semibold tracking-[-0.02em]">Investigate {server.label}</h2>
          <p className="mt-1 font-mono text-sm text-muted">{server.id} · {server.region} · {server.main_ip}</p>

          <label htmlFor={`${id}-r`} className="block mt-6 font-medium">What looks wrong?</label>
          <textarea
            id={`${id}-r`}
            name="reason"
            required
            maxLength={500}
            rows={3}
            autoFocus
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="CPU at 100% overnight, unknown process."
            aria-describedby={`${id}-h`}
            className="mt-2 w-full bg-ground border border-line rounded-xs p-3 text-base placeholder:text-muted/70 focus:border-muted outline-none"
          />
          <p id={`${id}-h`} className="mt-2 text-sm text-muted">
            Goes into the case log as the reason. First step: a snapshot of {server.label}. The server is not stopped.
          </p>
          {error && <p role="alert" className="mt-4 text-sm font-mono border border-line p-3 break-all">{error}</p>}

          <div className="mt-8 flex justify-end gap-3">
            <button type="button" className="btn" onClick={() => ref.current?.close()}>Cancel</button>
            <button type="submit" className="btn btn-primary" disabled={busy || !reason.trim()}>
              {busy ? 'Opening case...' : 'Open case'}
            </button>
          </div>
        </form>
      )}
    </dialog>
  )
}

// The case state machine (contracts/models.py CaseState), as the operator lives it.
const LIFECYCLE: [string, string, boolean][] = [
  ['snapshotting', 'Vultr snapshot of the server. Its ID becomes evidence item one.', false],
  ['restoring', 'A twin boots from that snapshot on a private VPC, behind an inbound-deny firewall.', false],
  ['sealed', 'Cloned disk mounted read-only, outbound traffic dropped. Both checks shown to you.', false],
  ['investigating', 'The agent writes and runs triage scripts against the copy, never the original.', false],
  ['reported', 'Findings with evidence and hashes. Containment proposed as exact API calls.', false],
  ['contained', 'You approve. Only now is production changed, and every response is logged.', true],
  ['closed', 'Twin destroyed, snapshot kept, case log sealed into a downloadable bundle.', false],
]

function Lifecycle() {
  return (
    <section aria-labelledby="lifecycle-t" className="mt-8 md:mt-14">
      <h2 id="lifecycle-t" className="label">After you open a case</h2>
      {/* One rail, seven stops. Phone: vertical rail on the left. Desktop: one horizontal rule. */}
      <ol className="mt-5 relative grid gap-y-5 pl-6 lg:pl-0 lg:grid-cols-7 lg:gap-x-6
        before:absolute before:left-[3px] before:top-1 before:bottom-1 before:w-px before:bg-line
        lg:before:left-0 lg:before:right-0 lg:before:top-[3px] lg:before:bottom-auto lg:before:h-px lg:before:w-auto">
        {LIFECYCLE.map(([state, text, human], i) => (
          <li key={state} className="relative lg:pt-6">
            <span aria-hidden="true" className={`absolute -left-6 top-1 lg:left-0 lg:top-0 size-[7px] rounded-full ${
              human ? 'bg-ink ring-4 ring-ground' : 'bg-agent ring-4 ring-ground'}`} />
            <p className="font-mono text-xs text-muted">
              {String(i + 1).padStart(2, '0')}{' '}
              <span className={human ? 'text-ink' : 'text-agent'}>{state}</span>
            </p>
            {human && <p className="mt-1 font-mono text-xs text-ink">the only step that touches production</p>}
            <p className="mt-1.5 text-sm text-muted leading-[1.5] max-w-[40ch]">{text}</p>
          </li>
        ))}
      </ol>
    </section>
  )
}

/** Dev only: POST /dev/fake-case runs the recorded shop-prod case end to end. */
function FakeCase() {
  const nav = useNavigate()
  const [busy, setBusy] = useState(false)
  return (
    <p className="mt-8 text-sm text-muted">
      Dev:{' '}
      <button
        type="button"
        disabled={busy}
        className="underline underline-offset-4 hover:text-ink"
        onClick={async () => {
          setBusy(true)
          try { nav(`/cases/${(await api.fakeCase()).id}`) } finally { setBusy(false) }
        }}
      >
        run a fake case on shop-prod
      </button>
    </p>
  )
}
