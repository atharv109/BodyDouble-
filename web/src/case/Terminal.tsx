import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import type { Action, ActionApplied, CaseState, DnsCaptured, Finding, SealCheck, StateChanged, Step } from '../api/types'
import { SEVERITY_ORDER } from '../api/types'
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

/** The twin, as a four-pane terminal: what ran, what the model thought, what the sandbox caught, what was logged. */
export function Terminal({ live }: { live: LiveCase }) {
  const sealed = SEALS.every((s) => live.seals[s.check]?.passed)
  const working = live.state === 'investigating' || live.state === 'sealed'
  const tail = working || live.state === 'reported' // follow through to the report, then stop
  const steps = Object.fromEntries(live.steps.map((s) => [s.id, s]))
  const started = live.log.filter((e) => e.name === 'step_started')
  const n = live.log.length

  return (
    <section aria-labelledby="col-twin" className="min-w-0" data-testid="col-twin">
      <div className="seal-frame term border border-line bg-panel rounded-xs" data-sealed={sealed} data-testid="twin-frame">
        <StatusBar live={live} />

        <div className="term-grid">
          <Pane id="commands" title="Commands + output" meta={`${live.steps.length} run`} tail={tail} count={n}>
            {started.length === 0 ? (
              <Empty>The agent starts writing triage scripts once the twin is sealed.</Empty>
            ) : (
              <ol className="grid gap-5" aria-live="polite" aria-relevant="additions" data-testid="step-feed">
                {started.map((e) => { const s = steps[e.data.step.id]; return s && <CommandBlock key={s.id} step={s} /> })}
              </ol>
            )}
            {working && <p aria-hidden="true" className="mt-3"><span className="prompt">$</span> <span className="cursor" /></p>}
          </Pane>

          {/* AI + sandbox together hold every finding and the DNS capture (case.spec scopes them by col-findings). */}
          <div className="contents" data-testid="col-findings">
            <Pane id="ai" title="AI reasoning" meta={`${live.findings.length} ${live.findings.length === 1 ? 'finding' : 'findings'}`}
              metaTestId="finding-count" tail={tail} count={n}>
              <AiFeed live={live} steps={steps} />
            </Pane>
            <Pane id="sandbox" title="Sandbox / network" meta="--network none" tail={tail} count={n}>
              <SandboxFeed live={live} steps={steps} />
            </Pane>
          </div>

          <Pane id="log" title="Seal + case log" meta={live.detail?.case.firewall_group_id ?? 'inbound deny'} tail={tail} count={n}>
            <CaseLog live={live} sealed={sealed} />
          </Pane>
        </div>
      </div>
    </section>
  )
}

function StatusBar({ live }: { live: LiveCase }) {
  const c = live.detail?.case
  const reached = new Set(live.transitions.map((t) => t.to))
  const at = live.state ? ORDER.indexOf(live.state) : -1
  const last = live.transitions[live.transitions.length - 1]
  return (
    <header className="border-b border-line px-4 md:px-5 pt-4 pb-3">
      <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
        <h2 id="col-twin" className="label">Twin</h2>
        <span className="font-mono text-xs text-muted min-w-0 truncate">
          {c?.twin_instance_id ?? 'not booted'}{c?.vpc_id ? ` · ${c.vpc_id}` : ''}{c?.snapshot_id ? ` · from ${c.snapshot_id}` : ''}
        </span>
      </div>
      <ol className="mt-3 grid grid-cols-7 gap-1" aria-label="Case progress">
        {RAIL.map((r) => {
          const i = ORDER.indexOf(r.state)
          const done = reached.has(r.state) && i < at
          const current = r.state === live.state
          return (
            <li key={r.state} className="min-w-0" aria-current={current ? 'step' : undefined} data-testid={`rail-${r.state}`}
              data-done={done || current}>
              <span aria-hidden="true" className={`block h-[3px] rounded-xs transition-colors duration-300 ${
                current ? 'bg-agent' : done ? 'bg-agent/55' : 'bg-line'}`} />
              <span className={`mt-1.5 block font-mono text-[11px] sm:text-xs ${current ? 'text-ink' : 'text-muted max-sm:sr-only'}`}>
                {r.label}<span className="sr-only">{current ? ' (current)' : done ? ' (done)' : ''}</span>
              </span>
            </li>
          )
        })}
      </ol>
      <p className="mt-2 font-mono text-xs text-muted min-h-[1.5em] wrap-anywhere" aria-live="polite" data-testid="state-detail">
        {at > 0 && <span className="sm:hidden" aria-hidden="true">{num(Math.min(at, 7))}/07 · </span>}
        {live.state === 'failed' ? <span className="text-ink">failed: {last?.detail}</span>
          : last ? <><span className="text-agent">{last.to}</span>{last.detail ? ` · ${last.detail}` : ''}</> : 'waiting for the control plane'}
      </p>
    </header>
  )
}

/** One terminal pane. Desktop: fixed height, scrolls inside, follows the tail while the case is live. */
function Pane({ id, title, meta, metaTestId, tail, count, children }: {
  id: string; title: string; meta: string; metaTestId?: string; tail: boolean; count: number; children: ReactNode
}) {
  const body = useRef<HTMLDivElement>(null)
  const pinned = useRef(true)
  useLayoutEffect(() => {
    const el = body.current
    if (el && tail && pinned.current) el.scrollTop = el.scrollHeight
  }, [count, tail])
  return (
    <section aria-labelledby={`pane-${id}-h`} className={`pane pane-${id}`} data-testid={`pane-${id}`}>
      <header className="pane-head">
        <h3 id={`pane-${id}-h`} className="text-ink">{title}</h3>
        <span className="text-muted truncate" data-testid={metaTestId}>{meta}</span>
      </header>
      <div ref={body} className="pane-body" tabIndex={0} role="region" aria-label={title}
        onScroll={(e) => { const el = e.currentTarget; pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 32 }}>
        {children}
      </div>
    </section>
  )
}

const Empty = ({ children }: { children: ReactNode }) => <p className="text-muted"># {children}</p>

function CommandBlock({ step: s }: { step: Step }) {
  const running = s.exit_code === null || s.exit_code === undefined
  const [copied, setCopied] = useState(false)
  const copy = () => navigator.clipboard?.writeText(s.code)
    .then(() => { setCopied(true); setTimeout(() => setCopied(false), 1200) }, () => {})
  return (
    <li className="latch" data-testid={`step-${s.id}`} data-status={running ? 'running' : 'done'}>
      <div className="flex flex-wrap items-baseline gap-x-2 text-muted">
        <span>#{num(s.seq)}</span>
        <span className="text-agent">{s.tool}</span>
        {s.kind === 'detonate' && <span className="border border-line rounded-xs px-1.5">no-network container</span>}
        <button type="button" className="term-btn ml-auto" onClick={copy}>
          {copied ? 'copied' : 'copy code'}<span className="sr-only"> for step {s.seq}, {s.tool}</span>
        </button>
      </div>
      <p className="text-muted"># {s.rationale}</p>
      <pre className="term-code"><span className="prompt" aria-hidden="true">$ </span>{s.code}</pre>
      {running ? (
        <p className="text-muted flex items-center gap-1.5"><span aria-hidden="true" className="running-dot size-1.5 rounded-full bg-agent" />running</p>
      ) : (
        <>
          {s.stdout && <pre className="term-out term-gutter">{s.stdout}</pre>}
          {s.stderr && <pre className="term-out term-gutter text-muted"><span className="sr-only">stderr: </span><span aria-hidden="true">2&gt; </span>{s.stderr}</pre>}
          {!s.stdout && !s.stderr && <p className="text-muted">(no output)</p>}
          <p className={s.exit_code === 0 ? 'text-muted' : 'text-ink'}>[exit {s.exit_code} · {s.duration_ms} ms]</p>
        </>
      )}
    </li>
  )
}

const Role = ({ r }: { r: 'planner' | 'solver' }) => (
  <span className={`role ${r === 'planner' ? 'text-agent' : 'text-ink'}`}>{r}</span>
)

function AiFeed({ live, steps }: { live: LiveCase; steps: Record<string, Step> }) {
  const items = live.log.filter((e) => e.name === 'step_started' || e.name === 'finding_added'
    || (e.name === 'state_changed' && (e.data as StateChanged).to_state === 'reported'))
  if (!items.length) return <Empty>The planner picks the first tool once the copy is sealed.</Empty>
  return (
    <ol className="grid gap-3" aria-live="polite" aria-relevant="additions">
      {items.map((e) => {
        if (e.name === 'step_started') {
          const s: Step = steps[e.data.step.id] ?? e.data.step
          const args = Object.keys(s.args ?? {}).length ? JSON.stringify(s.args) : '{}'
          return (
            <li key={e.seq} className="latch ai-line" data-testid={`ai-${s.id}`}>
              <Role r="planner" />
              <div className="min-w-0"><span className="text-agent">{s.tool}</span> <span className="text-muted wrap-anywhere">{args}</span>
                <p>{s.rationale}</p></div>
            </li>
          )
        }
        if (e.name === 'finding_added') {
          const f = e.data.finding as Finding
          return (
            <li key={e.seq} className="latch ai-line" data-testid={`ai-${f.id}`}>
              <Role r="solver" />
              <div className="min-w-0"><span className={f.severity === 'critical' || f.severity === 'high' ? 'text-finding' : 'text-muted'}>
                [{f.severity}]</span> {f.title} <span className="text-muted">({f.evidence_ids.join(', ')})</span></div>
            </li>
          )
        }
        return <Report key={e.seq} live={live} summary={(e.data as StateChanged).detail ?? ''} />
      })}
    </ol>
  )
}

/** The reporter's output: plain-English summary, findings by severity with their evidence, the fixes ranked. */
function Report({ live, summary }: { live: LiveCase; summary: string }) {
  const ev = evidenceIndex(live.detail)
  const sorted = [...live.findings].sort((a, b) => SEVERITY_ORDER[a.severity] - SEVERITY_ORDER[b.severity] || a.id.localeCompare(b.id))
  const ranked = [...live.actions].sort((a, b) => Number(b.recommended) - Number(a.recommended))
  return (
    <li className="latch" data-testid="ai-report">
      <div className="ai-line"><Role r="solver" /><p className="text-ink">report · {summary || `${sorted.length} findings`}</p></div>
      {sorted.length === 0 ? (
        <p className="mt-3 text-muted"># Nothing found. The copy looks clean.</p>
      ) : (
        <ol className="mt-3 grid gap-2">
          {sorted.map((f) => <FindingCard key={f.id} f={f} ev={ev} />)}
        </ol>
      )}
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

function SandboxFeed({ live, steps }: { live: LiveCase; steps: Record<string, Step> }) {
  const ev = evidenceIndex(live.detail)
  const items = live.log.filter((e) => e.name === 'dns_captured' || (e.name === 'step_started' && e.data.step.kind === 'detonate'))
  const blast = live.teardown?.blast_radius ?? live.detail?.blast_radius ?? null
  return (
    <div className="grid gap-4">
      {items.length === 0 && <Empty>Nothing detonated yet. Files run here with no network and a fake DNS resolver.</Empty>}
      {items.map((e) => {
        if (e.name === 'dns_captured') {
          const d = e.data as DnsCaptured
          return (
            <div key={e.seq} className="grid gap-2" data-testid={`sbx-dns-${num(e.seq)}`}>
              <p className="latch wrap-anywhere"><span className="text-finding">dns</span> {d.query} <span className="text-muted">-&gt;</span>{' '}
                {d.answered_with} <span className="text-muted">(sinkhole)</span></p>
              <DnsCard dns={d} evidence={ev[d.evidence_id]} />
            </div>
          )
        }
        const s: Step = steps[e.data.step.id] ?? e.data.step
        const target = (s.args as { path?: string })?.path ?? s.id
        const done = s.exit_code !== null && s.exit_code !== undefined
        return (
          <div key={e.seq} className="latch" data-testid={`sbx-${s.id}`}>
            <p className="wrap-anywhere"><span className="text-agent">detonate</span> {target} <span className="text-muted">· {s.id}</span></p>
            <p className="text-muted"># no network; a fake resolver answers every lookup and logs the name</p>
            {done ? (
              <>
                {(s.stdout ?? '').split('\n').filter(Boolean).map((l, i) => {
                  const k = l.includes(':') ? l.slice(0, l.indexOf(':')) : ''
                  return <p key={i} className="wrap-anywhere"><span className={k === 'dns' ? 'text-finding' : 'text-muted'}>{k}</span>{l.slice(k.length)}</p>
                })}
                <p className="text-muted">[exit {s.exit_code} · {s.duration_ms} ms]</p>
              </>
            ) : (
              <p className="text-muted flex items-center gap-1.5"><span aria-hidden="true" className="running-dot size-1.5 rounded-full bg-agent" />running</p>
            )}
          </div>
        )
      })}
      <div className="sbx-meters" data-testid="sandbox-meters">
        <dl>
          <div><dt>packets out</dt><dd data-testid="packets-out">{blast ? blast.packets_out : '..'}</dd></div>
          <div><dt>containers left</dt><dd data-testid="containers-left">{blast ? blast.containers_left : '..'}</dd></div>
        </dl>
        <p className="text-muted">{blast ? '# counted at teardown. Both must be 0.' : '# counted when the twin is torn down.'}</p>
      </div>
    </div>
  )
}

function CaseLog({ live, sealed }: { live: LiveCase; sealed: boolean }) {
  const items = live.log.filter((e) => e.name === 'state_changed' || e.name === 'action_proposed'
    || e.name === 'action_applied' || e.name === 'teardown_done')
  return (
    <div className="grid gap-4">
      <div>
        <p className="flex justify-between gap-2"><span className="text-muted"># seal checks</span>
          <span className={sealed ? 'text-agent' : 'text-muted'} data-testid="seal-status">
            {sealed ? 'sealed' : Object.keys(live.seals).length ? 'checking' : 'pending'}</span></p>
        <ul className="mt-1 grid gap-2">
          {SEALS.map((s) => {
            const r: SealCheck | undefined = live.seals[s.check]
            return (
              <li key={s.check} className={r ? 'latch' : ''} data-testid={`seal-${s.check}`}>
                <p className="flex gap-2"><span className={!r ? 'text-muted' : r.passed ? 'text-agent' : 'text-ink'}>
                  {!r ? '[ .. ]' : r.passed ? '[ ok ]' : '[FAIL]'}</span>
                  <span className={r ? '' : 'text-muted'}>{s.label}</span>
                  <span className="ml-auto text-muted">{!r ? 'pending' : r.passed ? 'passed' : 'FAILED'}</span></p>
                {r && <pre className="term-out text-muted sm:pl-[7ch]">{r.output}</pre>}
              </li>
            )
          })}
        </ul>
      </div>
      <ol className="grid gap-1.5" aria-label="Case log">
        <li className="text-muted"># case log, in order</li>
        {items.map((e) => <LogLine key={e.seq} e={e} />)}
      </ol>
      {live.teardown && (
        <p className="latch border-t border-line pt-3" data-testid="twin-teardown">
          <span className="text-agent">twin destroyed</span> · GET {live.teardown.twin_instance_id} returned{' '}
          {live.teardown.twin_status_code} · VPC {live.teardown.vpc_deleted ? 'deleted' : 'still present'}
        </p>
      )}
    </div>
  )
}

function LogLine({ e }: { e: LogItem }) {
  const seq = <span className="text-muted">{num(e.seq)}</span>
  if (e.name === 'state_changed') {
    const d = e.data as StateChanged
    return (
      <li className="latch log-line">{seq}
        <span className="min-w-0 wrap-anywhere"><span className="text-agent">{d.to_state}</span>{d.detail ? <span className="text-muted"> · {d.detail}</span> : null}</span>
      </li>
    )
  }
  if (e.name === 'teardown_done')
    return <li className="latch log-line">{seq}<span>teardown <span className="text-muted">· twin, VPC and firewall group deleted</span></span></li>
  const applied = e.name === 'action_applied'
  const a = (e.data as { action: Action }).action
  const res = applied ? (e.data as ActionApplied).api : null
  return (
    <li className="latch log-line" data-testid={`log-${applied ? 'applied' : 'proposed'}-${a.id}`}>
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
