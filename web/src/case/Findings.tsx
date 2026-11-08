import { useId, useState } from 'react'
import type { DnsCaptured, Evidence, Finding, Severity } from '../api/types'

const SEV_STYLE: Record<Severity, string> = {
  critical: 'bg-finding text-ground border-finding',
  high: 'text-finding border-finding',
  medium: 'text-ink border-finding/45',
  info: 'text-muted border-line',
}

export function DnsCard({ dns, evidence }: { dns: DnsCaptured; evidence?: Evidence }) {
  return (
    <article className="latch border border-finding bg-finding/10 rounded-xs p-4 font-sans" data-testid="dns-card" aria-label="DNS capture">
      <p className="font-mono text-xs text-finding uppercase tracking-[.06em]">Caught phoning home</p>
      <p className="mt-2 font-mono text-lg break-all leading-tight">{dns.query}</p>
      <p className="mt-2 text-sm">
        The detonated file tried to resolve this name. The fake resolver answered{' '}
        <span className="font-mono">{dns.answered_with}</span>; no packet left the sandbox.
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        <EvidenceChip id={dns.evidence_id} e={evidence} />
        <span className="font-mono text-xs text-muted self-center">from {dns.step_id}</span>
      </div>
    </article>
  )
}

export function FindingCard({ f, ev }: { f: Finding; ev: Record<string, Evidence> }) {
  return (
    <li className="latch border border-line bg-ground rounded-xs p-4" data-testid={`finding-${f.id}`} data-severity={f.severity}>
      <div className="flex items-center gap-2">
        <span className={`border rounded-xs px-1.5 py-px font-mono text-[11px] uppercase tracking-[.06em] ${SEV_STYLE[f.severity]}`}>
          {f.severity}
        </span>
        {f.mitre_id && <span className="font-mono text-xs text-muted">{f.mitre_id}</span>}
      </div>
      <h4 className="mt-2 font-sans text-[15px] font-medium leading-snug">{f.title}</h4>
      <p className="mt-1 font-sans text-sm text-muted">{f.summary}</p>
      <div className="mt-3 flex flex-wrap gap-2">
        {f.evidence_ids.map((id) => <EvidenceChip key={id} id={id} e={ev[id]} />)}
      </div>
    </li>
  )
}

const base = (p: string) => (p.includes(':') ? p : p.split('/').pop() || p)

/** Opens the hashed excerpt in place. Excerpts are quoted attacker text: shown, never followed. */
export function EvidenceChip({ id, e }: { id: string; e?: Evidence }) {
  const [open, setOpen] = useState(false)
  const pid = useId()
  return (
    <div className={open ? 'basis-full' : ''}>
      <button
        type="button"
        aria-expanded={open}
        aria-controls={pid}
        onClick={() => setOpen((o) => !o)}
        className="chip inline-flex items-center gap-1.5 border border-line rounded-xs px-2 py-1 font-mono text-xs hover:border-muted"
        data-testid={`chip-${id}`}
      >
        <span className="text-muted">{id}</span>
        <span>{e ? base(e.path) : '...'}</span>
        <span aria-hidden="true" className="text-muted">{open ? '−' : '+'}</span>
      </button>
      {open && (
        <div id={pid} className="latch mt-2 border border-line bg-ground rounded-xs p-3 text-xs" data-testid={`evidence-${id}`}>
          {e ? (
            <dl className="grid gap-2">
              <div><dt className="text-muted">Path</dt><dd className="font-mono break-all">{e.path}</dd></div>
              <div><dt className="text-muted">SHA-256</dt><dd className="font-mono break-all">{e.sha256}</dd></div>
              <div>
                <dt className="text-muted">Excerpt</dt>
                <dd><pre className="mt-1 font-mono whitespace-pre-wrap wrap-anywhere border-l border-line pl-3">{e.excerpt}</pre></dd>
              </div>
              {e.injection_flag && (
                <p className="text-finding">Text on the disk addressed to an AI. Quoted as evidence; the agent did not follow it.</p>
              )}
            </dl>
          ) : (
            <p className="text-muted">Loading evidence {id}...</p>
          )}
        </div>
      )}
    </div>
  )
}
