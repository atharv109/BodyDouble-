import { useEffect, useId, useState, type ReactNode } from 'react'
import { api, AUTH_REQUIRED, getOperator } from '../api/client'
import { Lifecycle } from '../routes/Servers'

/**
 * Every human endpoint needs an operator session (POST /auth/session). On load we re-mint it from the
 * stored name; with no name, or after a 401 we can't recover from, we ask who is operating.
 */
export function OperatorGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<'checking' | 'ask' | 'ready'>(() => (getOperator() ? 'checking' : 'ask'))
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const op = getOperator()
    if (op) api.session(op).then(() => setPhase('ready')).catch((e) => { setError(String(e.message ?? e)); setPhase('ask') })
    const onAuth = () => { api.signOut(); setPhase('ask') }
    window.addEventListener(AUTH_REQUIRED, onAuth)
    return () => window.removeEventListener(AUTH_REQUIRED, onAuth)
  }, [])

  if (phase === 'ready') return <>{children}</>
  if (phase === 'checking') return <p className="mx-auto max-w-[1600px] w-full px-4 md:px-6 py-20 font-mono text-sm text-muted">Starting operator session...</p>
  return <SignIn error={error} onDone={() => setPhase('ready')} />
}

function SignIn({ error: initial, onDone }: { error: string | null; onDone: () => void }) {
  const id = useId()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(initial)
  return (
    <section className="mx-auto max-w-[1600px] w-full px-4 md:px-6 pt-12 md:pt-20 pb-16 grid lg:grid-cols-12 gap-6">
      <h1 className="lg:col-span-12 text-[2.75rem] md:text-[4.5rem] xl:text-[5.5rem] leading-[0.95] font-semibold tracking-[-0.045em] -ml-[0.05em]">
        Who is operating?
      </h1>
      <div className="lg:col-span-5 xl:col-span-4">
        <p className="mt-2 text-muted max-w-[38ch]">
          Every approval to change production is signed with this name in the case log. Use your own, not a team alias.
        </p>
        <form
          className="mt-8"
          onSubmit={async (e) => {
            e.preventDefault()
            if (!name.trim()) return
            setBusy(true)
            setError(null)
            try { await api.session(name.trim()); onDone() } catch (err) { setError(String((err as Error).message ?? err)); setBusy(false) }
          }}
        >
          <label htmlFor={id} className="block font-medium">Operator name</label>
          <div className="mt-2 flex gap-3">
            <input id={id} value={name} onChange={(e) => setName(e.target.value)} autoFocus required maxLength={64} autoComplete="name"
              className="flex-1 min-w-0 bg-ground border border-line rounded-xs px-3 h-10 text-base focus:border-muted outline-none" />
            <button type="submit" className="btn btn-primary h-10" disabled={busy || !name.trim()}>{busy ? 'Starting...' : 'Start session'}</button>
          </div>
          {!name.trim() && !busy && <p className="mt-2 font-mono text-xs text-muted">Enter your name to start.</p>}
          {error && <p role="alert" className="mt-4 text-sm font-mono border border-line p-3 break-all">{error}</p>}
        </form>
      </div>
      {/* What the session is for: the same seven stops the case will walk through. */}
      <div className="lg:col-span-12"><Lifecycle /></div>
    </section>
  )
}
