import { useId, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { api, ApiError, getOperator } from '../api/client'

type Phase = 'idle' | 'busy' | 'ask' | 'unavailable' | 'down'

/**
 * Beat 9: open a live fake-mode case and land on it. The visitor passes the operator gate once
 * (approvals carry a name); with a stored name we re-mint the session and go straight through.
 * Real mode (operator password, /dev/fake-case off) and a dead API degrade to a message plus
 * a link to the console; the button stays usable.
 */
export function TryIt({ label }: { label: string }) {
  const navigate = useNavigate()
  const id = useId()
  const [phase, setPhase] = useState<Phase>('idle')
  const [name, setName] = useState('')
  const input = useRef<HTMLInputElement>(null)

  async function open(operator: string) {
    setPhase('busy')
    try {
      await api.session(operator)
      const c = await api.fakeCase()
      navigate(`/cases/${c.id}`, { viewTransition: true })
    } catch (e) {
      setPhase(e instanceof ApiError && (e.status === 404 || e.status === 401 || e.status === 403) ? 'unavailable' : 'down')
    }
  }

  async function start() {
    setPhase('busy')
    const { password_required } = await api.authConfig()
    if (password_required) return setPhase('unavailable') // real mode: no demo endpoint, no name-only sessions
    const op = getOperator()
    if (op) return open(op)
    setPhase('ask')
    requestAnimationFrame(() => input.current?.focus())
  }

  const submit = (e: FormEvent) => { e.preventDefault(); if (name.trim()) open(name.trim()) }

  return (
    <div className="mt-8">
      <button type="button" data-testid="try-it" className="btn btn-agent btn-xl" disabled={phase === 'busy'} onClick={start}>
        {phase === 'busy' ? 'Opening the case...' : label}
      </button>

      {phase === 'ask' && (
        <form className="tryit-ask" onSubmit={submit}>
          <label htmlFor={id} className="block font-medium">Operator name</label>
          <p className="text-sm text-muted mt-1">Approvals in the case log are signed with this name.</p>
          <div className="mt-3 flex gap-3 max-w-md">
            <input ref={input} id={id} value={name} onChange={(e) => setName(e.target.value)} required maxLength={64} autoComplete="name"
              className="flex-1 min-w-0 bg-ground border border-line rounded-xs px-3 h-11 text-base focus:border-muted outline-none" />
            <button type="submit" className="btn btn-primary h-11" disabled={!name.trim()}>Start session</button>
          </div>
        </form>
      )}

      <div role="status" className="tryit-msg">
        {phase === 'unavailable' && (
          <p>The live demo is not available on this deployment: it runs against real servers and needs an operator password. <Link to="/console" className="inline-link">Open the console</Link> to sign in.</p>
        )}
        {phase === 'down' && (
          <p>The demo backend is not answering right now. Try again in a minute, or <Link to="/console" className="inline-link">open the console</Link>.</p>
        )}
      </div>
    </div>
  )
}
