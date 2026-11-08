import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { api } from '../api/client'
import type { BlastRadius } from '../api/types'
import { useCase } from '../case/useCase'
import { useTitle } from '../ui/useTitle'

const BLAST: { key: keyof BlastRadius; label: string; note: string }[] = [
  { key: 'prod_writes_before_approval', label: 'Writes to production before approval', note: 'Counted from the case log of every Vultr call.' },
  { key: 'packets_out', label: 'Packets out of the sandbox', note: 'Egress drops and fake-resolver answers on the twin.' },
  { key: 'containers_left', label: 'Containers left running', note: 'Detonation containers still alive after teardown.' },
]

/** Screen 4. Tear the twin down, show what it cost (should be nothing), hand over the sealed evidence. */
export function CloseScreen() {
  const { id } = useParams()
  const live = useCase(id)
  const c = live.detail?.case
  useTitle(`Close and evidence, ${id}`)

  const [confirm, setConfirm] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const closed = live.state === 'closed' || !!live.teardown
  const blast = live.teardown?.blast_radius ?? live.detail?.blast_radius ?? null
  const clean = blast ? BLAST.every((b) => blast[b.key] === 0) : false
  const canClose = live.state === 'reported' || live.state === 'contained'
  const applied = live.actions.filter((a) => a.status === 'applied').length

  async function close() {
    if (!id) return
    setBusy(true)
    setError(null)
    try { await api.close(id) } catch (e) { setError(String((e as Error).message ?? e)) }
    setBusy(false)
    setConfirm(false)
  }

  return (
    <div className="mx-auto max-w-[1600px] w-full px-4 md:px-6 pt-10 md:pt-14 pb-16">
      <header className="grid lg:grid-cols-12 gap-6 items-end pb-8 border-b border-line">
        <div className="lg:col-span-8">
          <p className="label">Case <span className="font-mono normal-case tracking-normal">{id}</span> · {c?.instance_label ?? '...'}</p>
          <h1 className="mt-2 text-[2.5rem] md:text-[4rem] xl:text-[4.75rem] leading-[0.95] font-semibold tracking-[-0.04em] -ml-[0.05em]" data-testid="close-title">
            {!closed ? 'Close the case.' : clean ? 'Closed. Nothing escaped.' : 'Closed. Read the numbers.'}
          </h1>
        </div>
        <p className="lg:col-span-4 text-muted max-w-[44ch]">
          {closed
            ? 'The twin is gone. The snapshot is kept, and the case log, hashes and report are sealed in one bundle.'
            : 'Closing destroys the twin and its private network, keeps the snapshot, and seals the evidence. Production is not touched by closing.'}
        </p>
      </header>

      {/* Blast radius: the backend's numbers (F16), set as the page's image. */}
      <section aria-labelledby="blast-t" className="mt-10">
        <h2 id="blast-t" className="label">Blast radius</h2>
        <dl className="mt-4 grid md:grid-cols-3 border-t border-line" data-testid="blast">
          {BLAST.map((b, i) => {
            const v = blast?.[b.key]
            return (
              <div key={b.key} className={`py-6 md:pr-6 ${i > 0 ? 'border-t md:border-t-0 md:border-l md:pl-6' : ''} border-line`}>
                <dt className="text-sm">{b.label}</dt>
                <dd>
                  {/* Before teardown: an outlined 0, a placeholder for the number, not a result. */}
                  <span
                    className={`block mt-2 font-mono leading-none tracking-[-0.06em] text-[6rem] md:text-[8rem] ${v === undefined ? 'blast-pending' : ''} ${
                      v ? 'text-finding' : ''}`}
                    data-testid={`blast-${b.key}`}
                    data-value={v ?? ''}
                  >
                    {v === undefined ? <><span aria-hidden="true">0</span><span className="sr-only">counted at teardown</span></> : v}
                  </span>
                  {v === undefined && <span aria-hidden="true" className="block mt-3 font-mono text-xs text-muted">counted at teardown</span>}
                  <span className="block mt-3 text-xs text-muted">{b.note}</span>
                </dd>
              </div>
            )
          })}
        </dl>
      </section>

      <div className="mt-10 grid lg:grid-cols-12 gap-6">
        <section aria-labelledby="td-t" className="lg:col-span-7 border border-line bg-panel rounded-xs p-5 md:p-6">
          <h2 id="td-t" className="label">Teardown</h2>
          {live.teardown ? (
            <dl className="latch mt-4 grid grid-cols-[auto_1fr] gap-x-6 gap-y-2 font-mono text-sm" data-testid="teardown">
              <dt className="text-muted">event</dt><dd className="text-agent">teardown_done</dd>
              <dt className="text-muted">twin</dt><dd>{live.teardown.twin_instance_id} <span className="text-muted">GET returned</span> {live.teardown.twin_status_code}</dd>
              <dt className="text-muted">vpc</dt><dd>{c?.vpc_id ?? ''} {live.teardown.vpc_deleted ? 'deleted' : 'still present'}</dd>
              <dt className="text-muted">snapshot</dt><dd>{c?.snapshot_id ?? ''} kept</dd>
              <dt className="text-muted">approved</dt><dd>{applied} {applied === 1 ? 'change' : 'changes'} to production</dd>
            </dl>
          ) : (
            <>
              <p className="mt-4 text-sm">
                Twin <span className="font-mono">{c?.twin_instance_id ?? '...'}</span> on <span className="font-mono">{c?.vpc_id ?? '...'}</span> is
                still running. {applied ? `${applied} approved ${applied === 1 ? 'change has' : 'changes have'} been applied to production.` : 'No change has been applied to production.'}
              </p>
              {!canClose && !closed && (
                <p className="mt-3 text-sm text-muted">The case can be closed once the agent has reported. Current state: <span className="font-mono">{live.state ?? '...'}</span>.</p>
              )}
              <div className="mt-6 flex flex-wrap gap-3">
                {!confirm ? (
                  <button type="button" className="btn btn-primary" disabled={!canClose || busy} onClick={() => setConfirm(true)}>
                    Destroy the twin and seal evidence
                  </button>
                ) : (
                  <>
                    <button type="button" className="btn btn-primary" disabled={busy} onClick={close} autoFocus>
                      {busy ? 'Tearing down...' : `Yes, destroy ${c?.twin_instance_id ?? 'the twin'}`}
                    </button>
                    <button type="button" className="btn" disabled={busy} onClick={() => setConfirm(false)}>Keep it running</button>
                  </>
                )}
                <Link to={`/cases/${id}`} className="btn">Back to the case</Link>
              </div>
              {busy && <p className="mt-4 font-mono text-xs text-muted" aria-live="polite">waiting for teardown_done...</p>}
              {error && <p role="alert" className="mt-4 font-mono text-xs border border-line p-3 wrap-anywhere">{error}</p>}
            </>
          )}
        </section>

        <section aria-labelledby="ev-t" className="lg:col-span-5 border border-line rounded-xs p-5 md:p-6 flex flex-col">
          <h2 id="ev-t" className="label">Evidence bundle</h2>
          <p className="mt-4 text-sm">
            Snapshot ID, every file hash, the hash-chained case log and the report, as one zip you can send to a client or an analyst.
          </p>
          <p className="mt-2 font-mono text-xs text-muted">
            {live.detail ? `${live.detail.evidence.length} evidence items · ${live.findings.length} findings · ${live.lastSeq + 1} log entries` : '...'}
          </p>
          <div className="mt-auto pt-6">
            {closed ? (
              <a href={id ? api.bundleUrl(id) : '#'} download={`${id}-evidence.zip`} className="btn btn-agent" data-testid="download-bundle">
                Download evidence bundle
              </a>
            ) : (
              <button type="button" className="btn" disabled>Available after teardown</button>
            )}
          </div>
        </section>
      </div>
    </div>
  )
}
