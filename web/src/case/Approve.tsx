import { useEffect, useId, useRef, useState } from 'react'
import { api, getOperator } from '../api/client'
import type { Action, ApiResponse } from '../api/types'
import type { LiveCase } from './useCase'

const KIND: Record<string, string> = {
  quarantine_firewall: 'Quarantine firewall',
  revoke_ssh_key: 'Revoke SSH key',
  stop_instance: 'Halt the server',
  rotate_secrets: 'Rotate secrets',
}

type Sent = { state: 'sending' } | { state: 'done'; action: Action } | { state: 'error'; message: string }

/**
 * Screen 3. The only place production can change. Nothing is pre-checked and nothing is sent until the
 * Approve click; then one POST per checked action, in order, each followed by the API response it produced.
 */
export function ApproveDrawer({ live, caseId, open, onClose }: { live: LiveCase; caseId: string; open: boolean; onClose: () => void }) {
  const ref = useRef<HTMLDialogElement>(null)
  const tid = useId()
  const [checked, setChecked] = useState<Record<string, boolean>>({})
  const [sent, setSent] = useState<Record<string, Sent>>({})
  const [busy, setBusy] = useState(false)
  const operator = getOperator() ?? 'operator'

  useEffect(() => {
    const d = ref.current
    if (!d) return
    if (open && !d.open) d.showModal()
    if (!open && d.open) d.close()
  }, [open])

  const pending = live.actions.filter((a) => a.status === 'proposed')
  const picked = pending.filter((a) => checked[a.id])
  const appliedCount = live.actions.filter((a) => a.status === 'applied').length

  async function approve() {
    setBusy(true)
    for (const a of picked) {
      setSent((s) => ({ ...s, [a.id]: { state: 'sending' } }))
      try {
        const res = await api.approve(caseId, a.id, operator)
        setSent((s) => ({ ...s, [a.id]: { state: 'done', action: res } }))
      } catch (e) {
        setSent((s) => ({ ...s, [a.id]: { state: 'error', message: String((e as Error).message ?? e) } }))
      }
    }
    setChecked({})
    setBusy(false)
  }

  return (
    <dialog
      ref={ref}
      onClose={onClose}
      aria-labelledby={tid}
      className="drawer fixed inset-y-0 right-0 left-auto m-0 h-dvh max-h-dvh w-full sm:w-[min(640px,100vw)] max-w-none bg-panel text-ink border-l border-line p-0 backdrop:bg-black/60"
      data-testid="approve-drawer"
    >
      <div className="flex flex-col h-full">
        <header className="px-5 sm:px-8 pt-6 pb-5 border-b border-line">
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="label">Containment for production</p>
              <h2 id={tid} className="mt-2 text-2xl sm:text-3xl font-semibold tracking-[-0.025em]">Approve what touches the real server</h2>
            </div>
            <button type="button" className="btn shrink-0" onClick={() => ref.current?.close()}>Close</button>
          </div>
          <p className="mt-3 text-sm text-muted max-w-[56ch]">
            Each call below is sent to Vultr exactly as written, only for the boxes you tick, signed as{' '}
            <span className="font-mono text-ink">{operator}</span>.
          </p>
        </header>

        <ol className="flex-1 overflow-y-auto px-5 sm:px-8 py-5 grid content-start gap-3">
          {live.actions.map((a) => (
            <ActionRow
              key={a.id}
              a={a}
              checked={!!checked[a.id]}
              disabled={busy || a.status !== 'proposed'}
              onChange={(v) => setChecked((c) => ({ ...c, [a.id]: v }))}
              sent={sent[a.id]}
              response={(a.response as ApiResponse | null | undefined) ?? live.responses[a.id]}
            />
          ))}
          {live.actions.length === 0 && <li className="text-muted text-sm">No actions proposed yet.</li>}
        </ol>

        <footer className="px-5 sm:px-8 py-4 border-t border-line flex flex-wrap items-center gap-4">
          <p className="text-sm text-muted mr-auto" aria-live="polite">
            {picked.length ? `${picked.length} of ${pending.length} selected`
              : appliedCount && pending.length ? `${appliedCount} ${appliedCount === 1 ? 'change' : 'changes'} sent to Vultr · ${pending.length} left to review`
              : pending.length ? 'Nothing selected. Nothing will be sent.'
              : 'Every proposed action has been handled.'}
          </p>
          <button type="button" className="btn btn-agent" disabled={busy || picked.length === 0} onClick={approve} data-testid="approve-submit">
            {busy ? 'Applying...' : picked.length
              ? `Approve ${picked.length} ${picked.length === 1 ? 'action' : 'actions'}${picked.some((a) => a.kind === 'stop_instance') ? ', includes halt' : ''}`
              : 'Approve'}
          </button>
        </footer>
      </div>
    </dialog>
  )
}

function ActionRow({ a, checked, disabled, onChange, sent, response }: {
  a: Action; checked: boolean; disabled: boolean; onChange: (v: boolean) => void; sent?: Sent; response?: ApiResponse | null
}) {
  const id = useId()
  const applied = a.status === 'applied'
  const res = response ?? (sent?.state === 'done' ? (sent.action.response as ApiResponse | null) : null)
  return (
    <li className={`border rounded-xs ${applied ? 'border-agent/60' : checked ? 'border-ink' : 'border-line'} bg-ground`} data-testid={`action-${a.id}`} data-status={a.status}>
      <div className="flex gap-3 p-4">
        {applied ? (
          <svg width="16" height="16" viewBox="0 0 16 16" className="mt-1 shrink-0 text-agent" role="img" aria-label="applied">
            <path d="M3 8.5l3.2 3.2L13 4.8" fill="none" stroke="currentColor" strokeWidth="2" />
          </svg>
        ) : (
          <input
            id={id}
            type="checkbox"
            className="mt-1 size-4 accent-[var(--color-agent)] shrink-0"
            checked={checked}
            disabled={disabled}
            onChange={(e) => onChange(e.target.checked)}
            aria-describedby={`${id}-d`}
          />
        )}
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-x-3 gap-y-1">
            <label htmlFor={id} className="font-medium">{KIND[a.kind] ?? a.kind}</label>
            <span className={`font-mono text-xs ${applied ? 'text-agent' : 'text-muted'}`}>{a.status}{a.approved_by ? ` by ${a.approved_by}` : ''}</span>
            {a.kind === 'stop_instance' && !applied && (
              <span className="font-mono text-[11px] uppercase tracking-[.06em] border border-ink px-1.5 rounded-xs">takes the shop offline</span>
            )}
          </div>
          <p id={`${id}-d`} className="mt-1 text-sm text-muted">{a.description}</p>

          {a.api_method ? (
            <pre className="mt-3 font-mono text-xs whitespace-pre-wrap wrap-anywhere border-l-2 border-agent pl-3" data-testid={`call-${a.id}`}>
              <span className="text-agent">{a.api_method}</span> {a.api_path}
              {a.api_body ? `\n${JSON.stringify(a.api_body, null, 2)}` : ''}
            </pre>
          ) : (
            <p className="mt-3 font-mono text-xs text-muted border-l-2 border-line pl-3" data-testid={`call-${a.id}`}>
              No API call. Manual step for you; approving records it in the case log.
            </p>
          )}

          {sent?.state === 'sending' && <p className="mt-3 font-mono text-xs text-muted">sending...</p>}
          {sent?.state === 'error' && <p role="alert" className="mt-3 font-mono text-xs border border-line p-2 wrap-anywhere">{sent.message}</p>}
          {(applied || sent?.state === 'done') && (
            <div className="latch mt-3 border-l-2 border-ink pl-3" data-testid={`response-${a.id}`}>
              <p className="label">Response</p>
              {res ? (
                <pre className="mt-1.5 font-mono text-xs whitespace-pre-wrap wrap-anywhere">
                  <span className="text-agent">{res.status_code}</span> {res.method} {res.path}
                  {res.response != null ? `\n${JSON.stringify(res.response, null, 2)}` : ''}
                </pre>
              ) : (
                <p className="mt-1.5 font-mono text-xs text-muted">recorded, no API call made</p>
              )}
            </div>
          )}
        </div>
      </div>
    </li>
  )
}
