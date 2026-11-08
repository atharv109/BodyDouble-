import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import type { Action, ActionApplied, CaseState, DnsCaptured, Finding, SealCheck, StateChanged, Step } from '../api/types'
import { EVENT_NAMES, SEVERITY_ORDER } from '../api/types'
import { DnsCard, FindingCard } from './Findings'
import type { LiveCase, LogItem } from './useCase'
import { evidenceIndex } from './useCase'

// Everything in here that came off the twin (stdout, stderr, excerpts, alert text) is attacker-derived.
// It is only ever rendered as React text children: never innerHTML, never a link, never markdown.

const RAIL: { state: CaseState; label: string }[] = [
  { state: 'snapshotting', label: 'Snapshot' },
  { state: 'restoring', label: 'Restore' },
  { state: 'sealed', label: 'Seal' },
  { state: 'investigating', label: 'Inspect' },
  { state: 'reported', label: 'Report' },
  { state: 'contained', label: 'Contain' },
  { state: 'closed', label: 'Close' },
]
const ORDER: CaseState[] = ['opened', 'snapshotting', 'restoring', 'sealed', 'investigating', 'reported', 'contained', 'closed']
const SEALS = [
  { check: 'disk_read_only', label: 'Disk mounted read-only' },
  { check: 'egress_blocked', label: 'Outbound traffic dropped' },
]
const KIND: Record<string, string> = {
  quarantine_firewall: 'Quarantine firewall', revoke_ssh_key: 'Revoke SSH key', stop_instance: 'Stop server',
  rotate_secrets: 'Rotate secrets', manual_plan: 'Your plan',
}
const num = (n: number) => String(n).padStart(2, '0')
const isRunning = (s: Step) => s.exit_code === null || s.exit_code === undefined
const phaseOf = (s: CaseState | null) => (s ? RAIL.findIndex((r) => r.state === s) + 1 : 0) // 0 = opened / none
const reduced = () => typeof matchMedia !== 'undefined' && matchMedia('(prefers-reduced-motion: reduce)').matches

/* ------------------------------------------------------------------ status band */

/** The compact band across the top: where the case is, how far along, and the one thing to do next. */
export function StatusBand({ live, caseId, actions }: { live: LiveCase; caseId?: string; actions: ReactNode }) {
  const c = live.detail?.case
  const label = c?.instance_label ?? ''
  const events = Object.values(live.seen).reduce((a, b) => a + (b ?? 0), 0)
  const reached = new Set(live.transitions.map((t) => t.to))
  const at = live.state ? ORDER.indexOf(live.state) : -1
  const last = live.transitions[live.transitions.length - 1]
  const phase = phaseOf(live.state)
  const done = live.steps.filter((s) => !isRunning(s)).length
  const active = live.steps.length - done
  const severe = live.findings.filter((f) => f.severity === 'critical' || f.severity === 'high').length
  const sealed = SEALS.every((s) => live.seals[s.check]?.passed)

  return (
    <header className="band" data-testid="status-band">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-4">
        <div className="min-w-0">
          <p className="label flex flex-wrap items-center gap-x-3 gap-y-1">
            <span>Case <span className="font-mono normal-case tracking-normal text-ink">{caseId}</span></span>
            <span className="flex items-center gap-1.5 normal-case tracking-normal" aria-live="off" data-testid="stream-status">
              <span aria-hidden="true" className={`size-1.5 rounded-full ${live.connected ? 'bg-agent' : 'bg-muted/50'}`} />
              {live.connected ? 'live' : live.state === 'closed' ? 'closed' : 'reconnecting'} · {events} events
            </span>
          </p>
          <h1 className="mt-1 text-[1.75rem] md:text-[2.5rem] leading-[1.02] font-semibold tracking-[-0.035em] -ml-[0.04em]">
            {label || '...'} <span className="text-muted font-normal">and its twin</span>
          </h1>
        </div>
        {/* Phone: primary first and full width (column-reverse puts the approve button on top). */}
        <div className="w-full sm:w-auto sm:ml-auto flex flex-col-reverse sm:flex-row flex-wrap gap-3 [&>*]:justify-center max-sm:[&>*]:w-full">
          {actions}
        </div>
      </div>

      <div className="mt-5 grid gap-2 md:grid-cols-[9rem_minmax(0,1fr)] md:items-start md:gap-x-6">
        <p className="font-mono text-sm text-ink" data-testid="phase">
          <span className="text-agent">[{phase}/7]</span> {phase ? RAIL[phase - 1].label : live.state === 'failed' ? 'Failed' : 'Opened'}
        </p>
        <div className="min-w-0">
          <ol className="grid grid-cols-7 gap-1" aria-label="Case progress">
            {RAIL.map((r) => {
              const i = ORDER.indexOf(r.state)
              const isDone = reached.has(r.state) && i < at
              const current = r.state === live.state
              return (
                <li key={r.state} className="min-w-0" aria-current={current ? 'step' : undefined} data-testid={`rail-${r.state}`}
                  data-done={isDone || current}>
                  <span aria-hidden="true" className="rail-seg" data-state={current ? 'current' : isDone ? 'done' : 'todo'} />
                  <span className={`mt-1.5 block font-mono text-[11px] sm:text-xs ${current ? 'text-ink' : 'text-muted max-sm:sr-only'}`}>
                    {r.label}<span className="sr-only">{current ? ' (current)' : isDone ? ' (done)' : ''}</span>
                  </span>
                </li>
              )
            })}
          </ol>
          <p className="mt-1.5 font-mono text-xs text-muted min-h-[1.5em] wrap-anywhere" aria-live="polite" data-testid="state-detail">
            {live.state === 'failed' ? <span className="text-ink">failed: {last?.detail}</span>
              : last ? <><span className="text-agent">{last.to}</span>{last.detail ? ` · ${last.detail}` : ''}</> : 'waiting for the control plane'}
          </p>
        </div>
      </div>

      <dl className="band-stats">
        <div><dt>Commands</dt><dd>{done}/{live.steps.length} done{active ? <span className="text-agent">, {active} active</span> : null}</dd></div>
        <div><dt>Findings</dt><dd data-testid="finding-count" className={severe ? 'text-finding' : ''}>
          {live.findings.length}{severe ? <span className="text-muted">, {severe} high or critical</span> : null}</dd></div>
        <div><dt>Caught</dt><dd className={live.dns.length ? 'text-finding' : ''}>{live.dns.length} DNS {live.dns.length === 1 ? 'lookup' : 'lookups'}</dd></div>
        <div><dt>Seal</dt><dd className={sealed ? 'text-agent' : ''}>{sealed ? 'sealed' : Object.keys(live.seals).length ? 'checking' : 'pending'}</dd></div>
        <div className="min-w-0 max-sm:col-span-2"><dt>Twin</dt><dd className="truncate">
          {c?.twin_instance_id ?? 'not booted'}<span className="text-muted">{c?.vpc_id ? ` · ${c.vpc_id}` : ''}</span></dd></div>
      </dl>
    </header>
  )
}

/* ------------------------------------------------------------- investigation log */

/** The one chronological log: the planner's reasoning in full, each command folded under it, findings as they land. */
export function InvestigationLog({ live }: { live: LiveCase }) {
  const sealed = SEALS.every((s) => live.seals[s.check]?.passed)
  const working = live.state === 'investigating' || live.state === 'sealed'
  const tail = working || live.state === 'reported' // follow through to the report, then stop
  const steps = Object.fromEntries(live.steps.map((s) => [s.id, s]))
  const items = live.log.filter((e) => e.name === 'state_changed' || e.name === 'step_started'
    || e.name === 'finding_added' || e.name === 'dns_captured')

  const body = useRef<HTMLDivElement>(null)
  const [pinned, setPinned] = useState(true)
  const pinnedRef = useRef(true)
  useLayoutEffect(() => {
    const el = body.current
    if (el && tail && pinnedRef.current) el.scrollTop = el.scrollHeight
  }, [live.log.length, tail])
  const follow = () => {
    const el = body.current
    if (!el) return
    pinnedRef.current = true; setPinned(true)
    el.scrollTo({ top: el.scrollHeight, behavior: reduced() ? 'auto' : 'smooth' })
  }

  return (
    <section aria-labelledby="log-h" className="inv seal-frame" data-sealed={sealed} data-testid="twin-frame">
      <header className="pane-head">
        <h2 id="log-h" className="text-ink">Investigation log</h2>
        <span className="text-muted truncate">{sealed ? 'twin sealed · no inbound · no egress' : 'twin not sealed yet'}</span>
      </header>
      <div ref={body} className="pane-body inv-body" tabIndex={0} role="region" aria-label="Investigation log" data-testid="pane-commands"
        onScroll={(e) => {
          const el = e.currentTarget
          const p = el.scrollHeight - el.scrollTop - el.clientHeight < 32
          if (p !== pinnedRef.current) { pinnedRef.current = p; setPinned(p) }
        }}>
        <div data-testid="pane-ai">
        {items.length === 0 ? (
          <p className="text-muted"># Waiting for the control plane. The agent starts once the twin is sealed.</p>
        ) : (
          <ol className="grid gap-4" aria-live="polite" aria-relevant="additions" data-testid="investigation-log">
            {items.map((e) => <Entry key={e.seq} e={e} live={live} steps={steps} />)}
          </ol>
        )}
        {working && <p aria-hidden="true" className="mt-3"><span className="prompt">$</span> <span className="cursor" /></p>}
        </div>
      </div>
      {tail && !pinned && (
        <button type="button" className="term-btn follow-btn latch" onClick={follow}>
          <span aria-hidden="true">↓</span> follow live
        </button>
      )}
    </section>
  )
}

function Entry({ e, live, steps }: { e: LogItem; live: LiveCase; steps: Record<string, Step> }) {
  if (e.name === 'state_changed') {
    const d = e.data as StateChanged
    const p = phaseOf(d.to_state)
    return (
      <>
        <li className="phase-row latch">
          <span className="text-agent whitespace-nowrap">[{p}/7] {d.to_state}</span>
          {d.detail ? <span className="text-muted min-w-0 wrap-anywhere">{d.detail}</span> : null}
        </li>
        {d.to_state === 'reported' && <Report live={live} summary={d.detail ?? ''} />}
      </>
    )
  }
  if (e.name === 'step_started') {
    const s: Step = steps[e.data.step.id] ?? e.data.step
    return <StepEntry step={s} />
  }
  if (e.name === 'finding_added') {
    const f = e.data.finding as Finding
    const hot = f.severity === 'critical' || f.severity === 'high'
    return (
      <li className={`latch ai-line ${hot ? 'hot' : ''}`} data-testid={`ai-${f.id}`}>
        <Role r="solver" />
        <p className="min-w-0"><span className={hot ? 'text-finding' : 'text-muted'}>[{f.severity}]</span> {f.title}{' '}
          <span className="text-muted">({f.evidence_ids.join(', ')})</span></p>
      </li>
    )
  }
  const d = e.data as DnsCaptured
  return (
    <li data-testid={`sbx-dns-${num(e.seq)}`}>
      <DnsCard dns={d} evidence={evidenceIndex(live.detail)[d.evidence_id]} />
    </li>
  )
}

const Role = ({ r }: { r: 'planner' | 'solver' }) => (
  <span className={`role ${r === 'planner' ? 'text-agent' : 'text-ink'}`}>{r}</span>
)

/** One step: the planner's reason in full, the command folded beneath it (open it for code and output). */
function StepEntry({ step: s }: { step: Step }) {
  const running = isRunning(s)
  const args = Object.keys(s.args ?? {}).length ? JSON.stringify(s.args) : '{}'
  const first = s.code.split('\n')[0]
  const [copied, setCopied] = useState(false)
  const copy = () => navigator.clipboard?.writeText(s.code)
    .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200) }, () => {})
  return (
    <li id={`entry-${s.id}`} className="latch entry" data-testid={`step-${s.id}`} data-status={running ? 'running' : 'done'}>
      <div className="ai-line" data-testid={`ai-${s.id}`}>
        <Role r="planner" />
        <div className="min-w-0">
          <p className="text-ink">{s.rationale}</p>
          <p className="text-muted wrap-anywhere">
            #{num(s.seq)} <span className="text-agent">{s.tool}</span> {args}
            {s.kind === 'detonate' && <span className="ml-2 border border-line rounded-xs px-1.5 text-ink">no-network container</span>}
          </p>
        </div>
      </div>
      <div className="cmd-row">
        <details className="cmd">
          <summary>
            <span aria-hidden="true" className="chev">▸</span>
            <span className="cmd-line"><span className="prompt" aria-hidden="true">$ </span>{first}</span>
            {running
              ? <span className="cmd-status text-agent"><span aria-hidden="true" className="running-dot size-1.5 rounded-full bg-agent inline-block mr-1.5" />running</span>
              : <span className={`cmd-status ${s.exit_code === 0 ? 'text-muted' : 'text-finding'}`}>[exit {s.exit_code} · {s.duration_ms} ms]</span>}
            <span className="sr-only">, show command and output</span>
          </summary>
          <div className="cmd-body">
            <pre className="term-code"><span className="prompt" aria-hidden="true">$ </span>{s.code}</pre>
            {running ? <p className="text-muted">running</p> : (
              <>
                {s.stdout && <pre className="term-out term-gutter">{s.stdout}</pre>}
                {s.stderr && <pre className="term-out term-gutter text-muted"><span className="sr-only">stderr: </span><span aria-hidden="true">2&gt; </span>{s.stderr}</pre>}
                {!s.stdout && !s.stderr && <p className="text-muted">(no output)</p>}
              </>
            )}
          </div>
        </details>
        <button type="button" className="term-btn shrink-0" onClick={copy}>
          {copied ? 'copied' : 'copy code'}<span className="sr-only"> for step {s.seq}, {s.tool}</span>
        </button>
      </div>
    </li>
  )
}

/** The reporter's output: plain-English summary, findings by severity with their evidence, the fixes ranked. */
function Report({ live, summary }: { live: LiveCase; summary: string }) {
  const ev = evidenceIndex(live.detail)
  const sorted = [...live.findings].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] || a.id.localeCompare(b.id))
  const ranked = [...live.actions].sort((a, b) => Number(b.recommended) - Number(a.recommended))
  return (
    <li className="latch report" data-testid="ai-report">
      <div className="ai-line"><Role r="solver" /><p className="text-ink">report · {summary || `${sorted.length} findings`}</p></div>
      <div data-testid="col-findings">
      {sorted.length === 0 ? (
        <p className="mt-3 text-muted"># Nothing found. The copy looks clean.</p>
      ) : (
        <ol className="mt-3 grid gap-2 2xl:grid-cols-2">
          {sorted.map((f) => <FindingCard key={f.id} f={f} ev={ev} />)}
        </ol>
      )}
      {live.dns.map((d, i) => <div className="mt-2" key={`${d.evidence_id}-${i}`}><DnsCard dns={d} evidence={ev[d.evidence_id]} /></div>)}
      </div>
      {ranked.length > 0 && (
        <>
          <p className="mt-4 text-muted"># fixes, ranked. A human approves each one; the agent applies none.</p>
          <ol className="mt-1 grid gap-1">
            {ranked.map((a, i) => (
              <li key={a.id} className="ai-line" data-testid={`rank-${a.id}`}>
                <span className="role text-muted">{i + 1}.</span>
                <div className="min-w-0">
                  <span className={a.recommended ? 'text-agent' : ''}>{KIND[a.kind] ?? a.kind}</span>
                  {a.recommended && <span className="text-agent"> · recommended</span>}
                  <span className="text-muted"> · {a.status}</span>
                </div>
              </li>
            ))}
          </ol>
        </>
      )}
    </li>
  )
}

/* ---------------------------------------------------------------------- the rail */

/** Scroll the log to a step, open its command and put focus on it. */
function jumpTo(id: string) {
  const el = document.getElementById(`entry-${id}`)
  if (!el) return
  const d = el.querySelector('details')
  if (d) d.open = true
  el.scrollIntoView({ block: 'start', behavior: reduced() ? 'auto' : 'smooth' })
  el.querySelector<HTMLElement>('summary')?.focus({ preventScroll: true })
  el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash')
}

function RailSection({ id, title, meta, children, testId }: {
  id: string; title: string; meta?: ReactNode; children: ReactNode; testId?: string
}) {
  return (
    <section aria-labelledby={`rail-${id}-h`} className="rail-sec" data-testid={testId}>
      <header className="rail-head">
        <h2 id={`rail-${id}-h`}>{title}</h2>
        {meta != null && <span className="text-muted truncate">{meta}</span>}
      </header>
      {children}
    </section>
  )
}

function Glyph({ state }: { state: 'todo' | 'run' | 'done' | 'fail' | 'wait' | 'skip' }) {
  const g = { todo: '○', run: '◌', done: '●', fail: '×', wait: '◇', skip: '–' }[state]
  return <span aria-hidden="true" className={`glyph glyph-${state}`}>{g}</span>
}

/** The narrower rail: what is running, what is sealed, what the sandbox caught, the raw log behind a fold. */
export function TaskRail({ live }: { live: LiveCase }) {
  const sealed = SEALS.every((s) => live.seals[s.check]?.passed)
  const done = live.steps.filter((s) => !isRunning(s)).length
  const awaiting = live.actions.filter((a) => a.status === 'proposed').length
  return (
    <div className="rail" data-testid="pane-log">
      <RailSection id="tasks" title="Tasks" meta={`${done}/${live.steps.length} commands`} testId="pane-tasks">
        <p className="task-group">
          <span>Seal</span>
          <span className={sealed ? 'text-agent' : 'text-muted'} data-testid="seal-status">
            {sealed ? 'sealed' : Object.keys(live.seals).length ? 'checking' : 'pending'}</span>
        </p>
        <ul className="grid gap-px">
          {SEALS.map((s) => {
            const r: SealCheck | undefined = live.seals[s.check]
            return (
              <li key={s.check} className={r ? 'latch' : ''} data-testid={`seal-${s.check}`}>
                <details className="task-fold">
                  <summary className="task">
                    <Glyph state={!r ? 'todo' : r.passed ? 'done' : 'fail'} />
                    <span className={`min-w-0 ${r ? '' : 'text-muted'}`}>{s.label}</span>
                    <span className={`ml-auto shrink-0 ${!r || r.passed ? 'text-muted' : 'text-finding'}`}>
                      {!r ? 'pending' : r.passed ? 'passed' : 'FAILED'}</span>
                  </summary>
                  {r && <pre className="term-out text-muted task-out">{r.output}</pre>}
                </details>
              </li>
            )
          })}
        </ul>

        <p className="task-group mt-4"><span>Inspect</span><span className="text-muted">{done}/{live.steps.length}</span></p>
        {live.steps.length === 0 ? <p className="text-muted"># no commands yet</p> : (
          <ol className="grid gap-px">
            {live.steps.map((s) => {
              const running = isRunning(s)
              return (
                <li key={s.id} className="latch" data-testid={`task-${s.id}`}>
                  <button type="button" className="task task-btn" onClick={() => jumpTo(s.id)}>
                    <Glyph state={running ? 'run' : s.exit_code === 0 ? 'done' : 'fail'} />
                    <span className="min-w-0 truncate">{s.tool}</span>
                    <span className={`ml-auto shrink-0 ${running ? 'text-agent' : s.exit_code === 0 ? 'text-muted' : 'text-finding'}`}>
                      {running ? 'running' : s.exit_code === 0 ? 'done' : `exit ${s.exit_code}`}</span>
                    <span className="sr-only">, show step {s.seq} in the log</span>
                  </button>
                </li>
              )
            })}
          </ol>
        )}

        {live.actions.length > 0 && (
          <>
            <p className="task-group mt-4"><span>Fixes</span>
              <span className={awaiting ? 'text-agent' : 'text-muted'}>{awaiting ? `${awaiting} awaiting you` : 'decided'}</span></p>
            <ul className="grid gap-px">
              {[...live.actions].sort((a, b) => Number(b.recommended) - Number(a.recommended)).map((a) => (
                <li key={a.id} className="task latch">
                  <Glyph state={a.status === 'applied' ? 'done' : a.status === 'proposed' ? 'wait' : 'skip'} />
                  <span className="min-w-0 truncate">{KIND[a.kind] ?? a.kind}
                    {a.recommended && <span className="text-agent"> · rec.<span className="sr-only">ommended</span></span>}</span>
                  <span className={`ml-auto shrink-0 ${a.status === 'applied' ? 'text-agent' : 'text-muted'}`}>{a.status}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </RailSection>

      <Sandbox live={live} />
      <CaseLog live={live} />

      <RailSection id="events" title="Event log" testId="pane-events">
        <details className="fold">
          <summary><span aria-hidden="true" className="chev">▸</span> count per stream event</summary>
          <ul className="mt-2 grid grid-cols-[1fr_auto] gap-x-4 gap-y-0.5" data-testid="event-ledger">
            {EVENT_NAMES.map((n) => (
              <li key={n} data-event={n} data-count={live.seen[n] ?? 0} className="contents">
                <span className={live.seen[n] ? 'text-ink' : 'text-muted'}>{n}</span>
                <span className={`text-right ${live.seen[n] ? 'text-agent' : 'text-muted'}`}>{live.seen[n] ?? 0}</span>
              </li>
            ))}
          </ul>
        </details>
      </RailSection>
    </div>
  )
}

function Sandbox({ live }: { live: LiveCase }) {
  const steps = Object.fromEntries(live.steps.map((s) => [s.id, s]))
  const runs = live.log.filter((e) => e.name === 'step_started' && e.data.step.kind === 'detonate')
  const blast = live.teardown?.blast_radius ?? live.detail?.blast_radius ?? null
  return (
    <RailSection id="sandbox" title="Sandbox / network" meta="--network none" testId="pane-sandbox">
      <div className="grid gap-1.5">
        {runs.length === 0 && live.dns.length === 0 && <p className="text-muted"># nothing detonated yet</p>}
        {runs.map((e) => {
          const s: Step = steps[e.data.step.id] ?? e.data.step
          const target = (s.args as { path?: string })?.path ?? s.id
          return (
            <p key={e.seq} className="latch wrap-anywhere" data-testid={`sbx-${s.id}`}>
              <span className="text-agent">detonate</span> {target}{' '}
              <span className="text-muted">{isRunning(s) ? '· running' : `· exit ${s.exit_code}`}</span>
            </p>
          )
        })}
        {live.dns.map((d, i) => (
          <div key={i} className="grid gap-1">
            <p className="latch wrap-anywhere"><span className="text-finding">dns</span> {d.query} <span className="text-muted">-&gt;</span> {d.answered_with}</p>
            <DnsCard dns={d} evidence={evidenceIndex(live.detail)[d.evidence_id]} />
          </div>
        ))}
      </div>
      <dl className="sbx-meters mt-3" data-testid="sandbox-meters">
        <div><dt>packets out</dt><dd data-testid="packets-out">{blast ? blast.packets_out : '..'}</dd></div>
        <div><dt>containers left</dt><dd data-testid="containers-left">{blast ? blast.containers_left : '..'}</dd></div>
      </dl>
      <p className="mt-1 text-muted">{blast ? '# counted at teardown. Both must be 0.' : '# counted when the twin is torn down.'}</p>
    </RailSection>
  )
}

function CaseLog({ live }: { live: LiveCase }) {
  const items = live.log.filter((e) => e.name === 'state_changed' || e.name === 'action_proposed'
    || e.name === 'action_applied' || e.name === 'teardown_done')
  return (
    <RailSection id="log" title="Case log" meta={live.detail?.case.firewall_group_id ?? 'inbound deny'}>
      {live.teardown && (
        <p className="latch mb-2" data-testid="twin-teardown">
          <span className="text-agent">twin destroyed</span> · GET {live.teardown.twin_instance_id} returned{' '}
          {live.teardown.twin_status_code} · VPC {live.teardown.vpc_deleted ? 'deleted' : 'still present'}
        </p>
      )}
      <details className="fold">
        <summary><span aria-hidden="true" className="chev">▸</span> {items.length} entries, each Vultr API call</summary>
        <ol className="mt-2 grid gap-1.5" aria-label="Case log">
          {items.map((e) => <LogLine key={e.seq} e={e} />)}
        </ol>
      </details>
    </RailSection>
  )
}

function LogLine({ e }: { e: LogItem }) {
  const seq = <span className="text-muted">{num(e.seq)}</span>
  if (e.name === 'state_changed') {
    const d = e.data as StateChanged
    return (
      <li className="log-line">{seq}
        <span className="min-w-0 wrap-anywhere"><span className="text-agent">{d.to_state}</span>{d.detail ? <span className="text-muted"> · {d.detail}</span> : null}</span>
      </li>
    )
  }
  if (e.name === 'teardown_done')
    return <li className="log-line">{seq}<span>teardown <span className="text-muted">· twin, VPC and firewall group deleted</span></span></li>
  const applied = e.name === 'action_applied'
  const a = (e.data as { action: Action }).action
  const res = applied ? (e.data as ActionApplied).api : null
  return (
    <li className="log-line" data-testid={`log-${applied ? 'applied' : 'proposed'}-${a.id}`}>
      {seq}
      <div className="min-w-0">
        <span className={applied ? 'text-agent' : ''}>{applied ? `${a.status} by ${a.approved_by ?? 'operator'}` : 'proposed'}</span>{' '}
        {KIND[a.kind] ?? a.kind}{a.recommended && !applied ? <span className="text-muted"> (recommended)</span> : null}
        {a.api_method
          ? <pre className="term-out text-muted">{`${a.api_method} ${a.api_path}${a.api_body ? ` ${JSON.stringify(a.api_body)}` : ''}${res ? `\n-> ${res.status_code}` : ''}`}</pre>
          : <p className="text-muted">no API call</p>}
      </div>
    </li>
  )
}
