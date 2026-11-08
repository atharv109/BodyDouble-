import type { CaseState, Step } from '../api/types'
import type { LiveCase } from './useCase'

const RAIL: { state: CaseState; label: string; major: boolean }[] = [
  { state: 'snapshotting', label: 'Snapshot', major: true },
  { state: 'restoring', label: 'Restore', major: true },
  { state: 'sealed', label: 'Seal', major: true },
  { state: 'investigating', label: 'Inspect', major: false },
  { state: 'reported', label: 'Report', major: false },
  { state: 'contained', label: 'Contain', major: false },
  { state: 'closed', label: 'Close', major: false },
]
const ORDER: CaseState[] = ['opened', 'snapshotting', 'restoring', 'sealed', 'investigating', 'reported', 'contained', 'closed']

const SEALS = [
  { check: 'disk_read_only', label: 'Disk mounted read-only' },
  { check: 'egress_blocked', label: 'Outbound traffic dropped' },
]

/** Centre column: the twin, where all the work happens. */
export function Twin({ live }: { live: LiveCase }) {
  const c = live.detail?.case
  const sealed = SEALS.every((s) => live.seals[s.check]?.passed)
  const reached = new Set(live.transitions.map((t) => t.to))
  const failed = live.state === 'failed'
  const at = live.state ? ORDER.indexOf(live.state) : -1
  const last = live.transitions[live.transitions.length - 1]

  return (
    <section aria-labelledby="col-twin" className="flex flex-col gap-4 min-w-0" data-testid="col-twin">
      <header className="flex items-baseline justify-between gap-3">
        <h2 id="col-twin" className="label">Twin</h2>
        <span className="font-mono text-xs text-muted truncate">
          {c?.twin_instance_id ?? 'not booted'}{c?.vpc_id ? ` · ${c.vpc_id}` : ''}{c?.firewall_group_id ? ` · ${c.firewall_group_id}` : ''}
        </span>
      </header>

      <div className="seal-frame border border-line bg-panel rounded-xs" data-sealed={sealed} data-testid="twin-frame">
        {/* state progress */}
        <div className="p-5">
          <ol className="grid grid-cols-7 gap-1" aria-label="Case progress">
            {RAIL.map((r) => {
              const i = ORDER.indexOf(r.state)
              const done = reached.has(r.state) && i < at
              const current = r.state === live.state
              return (
                <li key={r.state} className="min-w-0" aria-current={current ? 'step' : undefined} data-testid={`rail-${r.state}`}
                  data-done={done || current}>
                  <span aria-hidden="true" className={`block h-[3px] rounded-xs transition-colors duration-300 ${
                    current ? 'bg-agent' : done ? 'bg-agent/55' : 'bg-line'}`} />
                  {/* phone: only the current label shows; the others stay for screen readers */}
                  <span className={`mt-2 block font-mono text-[11px] sm:text-xs ${current ? 'text-ink' : 'text-muted max-sm:sr-only'}`}>
                    {r.label}
                    <span className="sr-only">{current ? ' (current)' : done ? ' (done)' : ''}</span>
                  </span>
                </li>
              )
            })}
          </ol>
          {at > 0 && (
            <p className="sm:hidden mt-2 font-mono text-xs text-muted" aria-hidden="true">
              {String(Math.min(at, 7)).padStart(2, '0')} / 07 · <span className="text-ink">{RAIL[Math.min(at, 7) - 1]?.label}</span>
              {RAIL[at] ? <> · next {RAIL[at].label}</> : null}
            </p>
          )}
          <p className="mt-4 font-mono text-xs text-muted min-h-[1.5em]" aria-live="polite" data-testid="state-detail">
            {failed ? <span className="text-ink">failed: {last?.detail}</span>
              : last ? <><span className="text-agent">{last.to}</span>{last.detail ? ` · ${last.detail}` : ''}</> : 'waiting for the control plane'}
          </p>
        </div>

        {/* seal checks */}
        <div className="border-t border-line p-5">
          <div className="flex items-baseline justify-between">
            <h3 className="label">Seal checks</h3>
            <span className={`font-mono text-xs ${sealed ? 'text-agent' : 'text-muted'}`} data-testid="seal-status">
              {sealed ? 'sealed' : Object.keys(live.seals).length ? 'checking' : 'pending'}
            </span>
          </div>
          <ul className="mt-3 grid gap-3">
            {SEALS.map((s) => {
              const r = live.seals[s.check]
              return (
                <li key={s.check} className={r ? 'latch' : ''} data-testid={`seal-${s.check}`}>
                  <div className="flex items-center gap-2 text-sm">
                    <Mark state={!r ? 'pending' : r.passed ? 'pass' : 'fail'} />
                    <span className={r ? '' : 'text-muted'}>{s.label}</span>
                    <span className="ml-auto font-mono text-xs text-muted">{!r ? 'pending' : r.passed ? 'passed' : 'FAILED'}</span>
                  </div>
                  {r && <pre className="mt-1.5 ml-6 font-mono text-xs text-muted whitespace-pre-wrap wrap-anywhere">{r.output}</pre>}
                </li>
              )
            })}
          </ul>
        </div>
      </div>

      {live.teardown && (
        <p className="latch border border-line rounded-xs p-4 font-mono text-xs" data-testid="twin-teardown">
          <span className="text-agent">twin destroyed</span> · GET {live.teardown.twin_instance_id} returned{' '}
          {live.teardown.twin_status_code} · VPC {live.teardown.vpc_deleted ? 'deleted' : 'still present'}
        </p>
      )}

      {/* live step feed */}
      <div className="flex items-baseline justify-between mt-2">
        <h3 className="label">Steps on the copy</h3>
        <span className="font-mono text-xs text-muted">{live.steps.length} run</span>
      </div>
      {live.steps.length === 0 ? (
        <p className="text-sm text-muted border border-dashed border-line rounded-xs p-5">
          The agent starts writing triage scripts once the twin is sealed.
        </p>
      ) : (
        <ol className="grid gap-2" aria-live="polite" aria-relevant="additions" data-testid="step-feed">
          {live.steps.map((s) => <StepItem key={s.id} step={s} />)}
        </ol>
      )}
    </section>
  )
}

function Mark({ state }: { state: 'pending' | 'pass' | 'fail' }) {
  if (state === 'pass')
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" className="text-agent shrink-0">
        <rect x="0.75" y="0.75" width="14.5" height="14.5" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
        <path d="M4.5 8.2l2.3 2.3 4.7-5" fill="none" stroke="currentColor" strokeWidth="1.6" />
      </svg>
    )
  if (state === 'fail')
    return (
      <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" className="shrink-0">
        <rect x="0.75" y="0.75" width="14.5" height="14.5" rx="2" fill="currentColor" />
        <path d="M5 5l6 6M11 5l-6 6" stroke="var(--color-ground)" strokeWidth="1.6" />
      </svg>
    )
  return (
    <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true" className="text-line shrink-0">
      <rect x="0.75" y="0.75" width="14.5" height="14.5" rx="2" fill="none" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  )
}

function StepItem({ step: s }: { step: Step }) {
  const running = s.exit_code === null || s.exit_code === undefined
  const out = [s.stdout, s.stderr].filter(Boolean).join('\n')
  return (
    <li className="latch border border-line bg-panel rounded-xs" data-testid={`step-${s.id}`} data-status={running ? 'running' : 'done'}>
      <div className="px-4 pt-3 pb-3">
        <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-xs">
          <span className="text-muted">#{String(s.seq).padStart(2, '0')}</span>
          <span className="text-agent font-medium">{s.tool}</span>
          {s.kind === 'detonate' && <span className="border border-line rounded-xs px-1.5 text-muted">no-network container</span>}
          <span className="ml-auto flex items-center gap-1.5 text-muted">
            {running ? (
              <><span aria-hidden="true" className="running-dot size-1.5 rounded-full bg-agent" />running</>
            ) : (
              <>exit {s.exit_code} · {s.duration_ms} ms</>
            )}
          </span>
        </div>
        <p className="mt-1.5 text-sm">{s.rationale}</p>
      </div>
      <details className="border-t border-line group/code">
        <summary className="px-4 py-2 font-mono text-xs text-muted hover:text-ink flex items-center gap-2">
          <span className="chev" aria-hidden="true">›</span> Code<span className="sr-only"> for step {s.seq}, {s.tool}</span>
        </summary>
        <pre className="px-4 pb-3 font-mono text-xs whitespace-pre-wrap wrap-anywhere text-ink/90">{s.code}</pre>
      </details>
      <details className="border-t border-line" open={!running && s.kind === 'detonate'}>
        <summary className="px-4 py-2 font-mono text-xs text-muted hover:text-ink flex items-center gap-2">
          <span className="chev" aria-hidden="true">›</span> Output
          {!running && (() => { const n = out ? out.split('\n').length : 0; return ` (${n} ${n === 1 ? 'line' : 'lines'})` })()}
          <span className="sr-only"> for step {s.seq}, {s.tool}</span>
        </summary>
        <pre className="px-4 pb-3 font-mono text-xs whitespace-pre-wrap wrap-anywhere text-ink/90">{running ? 'waiting...' : out || '(no output)'}</pre>
      </details>
    </li>
  )
}
