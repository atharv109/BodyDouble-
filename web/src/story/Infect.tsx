import { useId, useRef, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router'
import { api, ApiError, getOperator } from '../api/client'
import type { Attack } from '../api/types'
import { attacks } from './content'

type Phase = 'idle' | 'busy' | 'ask' | 'unavailable' | 'down'

/**
 * The climax: the visitor plants attacks on a fresh fake server (POST /dev/infect), its sensor fires,
 * and they land on the case the alert opened. Same gate and same graceful failure as before: real mode
 * (operator password, /dev/infect 404) and a dead API end in a message plus a console link.
 */
export function Infect() {
  const navigate = useNavigate()
  const id = useId()
  const [picked, setPicked] = useState<Attack[]>([])
  const [phase, setPhase] = useState<Phase>('idle')
  const [name, setName] = useState('')
  const input = useRef<HTMLInputElement>(null)

  const toggle = (a: Attack) => setPicked((p) => (p.includes(a) ? p.filter((x) => x !== a) : [...p, a]))

  async function run(operator: string) {
    setPhase('busy')
    try {
      await api.session(operator)
      const r = await api.infect(picked)
      navigate(`/cases/${r.case_id}`, { viewTransition: true })
    } catch (e) {
      setPhase(e instanceof ApiError && (e.status === 404 || e.status === 401 || e.status === 403) ? 'unavailable' : 'down')
    }
  }

  async function start() {
    setPhase('busy')
    const { password_required } = await api.authConfig()
    if (password_required) return setPhase('unavailable') // real mode: no demo endpoint, no name-only sessions
    const op = getOperator()
    if (op) return run(op)
    setPhase('ask')
    requestAnimationFrame(() => input.current?.focus())
  }

  const submit = (e: FormEvent) => { e.preventDefault(); if (name.trim()) run(name.trim()) }
  const n = picked.length

  return (
    <div className="infect">
      <fieldset className="attacks">
        <legend className="sr-only">Attacks to plant</legend>
        {attacks.map((a) => {
          const on = picked.includes(a.value)
          return (
            <label key={a.value} className="attack" data-on={on || undefined} data-testid={`attack-${a.value}`}>
              <input type="checkbox" className="attack-box" checked={on} onChange={() => toggle(a.value)} />
              <span className="attack-name">{a.name}</span>
              <span className="attack-path font-mono">{a.path}</span>
            </label>
          )
        })}
      </fieldset>

      <p className="infect-readout" aria-live="polite">
        {n ? <><span className="text-finding">{n} planted</span> · its sensor is armed · expect {n === 1 ? 'that finding' : 'those findings'} and nothing else</>
          : 'Nothing planted: a clean control. Expect zero findings.'}
      </p>

      <button type="button" data-testid="infect" className="btn btn-agent btn-xl infect-go" disabled={phase === 'busy'} onClick={start}>
        {phase === 'busy' ? 'Planting...' : n ? `Infect a server with ${n} ${n === 1 ? 'attack' : 'attacks'}` : 'Run a clean server'}
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
