import { useEffect, useId, useState, type ReactNode } from 'react'
import { api, ApiError, AUTH_REQUIRED, getOperator } from '../api/client'
import { Lifecycle } from '../routes/Servers'

/**
 * Every human endpoint needs an operator session (POST /auth/session). On load we re-mint it from the
 * stored name; with no name, or after a 401 we can't recover from, we ask who is operating.
 */
export function OperatorGate({ children }: { children: ReactNode }) {
  const [phase, setPhase] = useState<'checking' | 'ask' | 'ready'>('checking')
  const [error, setError] = useState<string | null>(null)
  const [needsPassword, setNeedsPassword] = useState(false)

  useEffect(() => {
    const onAuth = () => { api.signOut(); setPhase('ask') }
    window.addEventListener(AUTH_REQUIRED, onAuth)
    const fail = (e: Error) => { setError(String(e.message ?? e)); setPhase('ask') }
    api.authConfig().then(({ password_required }) => {
      setNeedsPassword(password_required)
      const op = getOperator()
      if (!op) return setPhase('ask')
      // Fake mode: re-mint from the stored name. Password mode: the password isn't stored, so only an
      // existing cookie session lets us in; a 401 here sends the operator to the gate.
      if (!password_required) api.session(op).then(() => setPhase('ready')).catch(fail)
      else api.instances().then(() => setPhase('ready')).catch(() => setPhase('ask'))
    })
    return () => window.removeEventListener(AUTH_REQUIRED, onAuth)
  }, [])

  if (phase === 'ready') return <>{children}</>
  if (phase === 'checking') return <p className="mx-auto max-w-[1600px] w-full px-4 md:px-6 py-20 font-mono text-sm text-muted">Starting operator session...</p>
  return <SignIn error={error} needsPassword={needsPassword} onDone={() => setPhase('ready')} />
}

function SignIn({ error: initial, needsPassword, onDone }: { error: string | null; needsPassword: boolean; onDone: () => void }) {
  const id = useId()
  const pwId = useId()
  const [name, setName] = useState(() => (needsPassword ? getOperator() ?? '' : ''))
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(initial)
  const ready = !!name.trim() && (!needsPassword || !!password)
  const submit = (
    <button type="submit" className="btn btn-primary h-10" disabled={busy || !ready}>{busy ? 'Starting...' : 'Start session'}</button>
  )
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
            if (!ready) return
            setBusy(true)
            setError(null)
            try { await api.session(name.trim(), needsPassword ? password : undefined); onDone() } catch (err) {
              setError(needsPassword && err instanceof ApiError && err.status === 401 ? 'Wrong operator password' : String((err as Error).message ?? err))
              setPassword('')
              setBusy(false)
            }
          }}
        >
          <label htmlFor={id} className="block font-medium">Operator name</label>
          <div className="mt-2 flex gap-3">
            <input id={id} value={name} onChange={(e) => setName(e.target.value)} autoFocus required maxLength={64} autoComplete="name"
              className="flex-1 min-w-0 bg-ground border border-line rounded-xs px-3 h-10 text-base focus:border-muted outline-none" />
            {!needsPassword && submit}
          </div>
          {needsPassword && (
            <>
              <label htmlFor={pwId} className="mt-5 block font-medium">Operator password</label>
              <div className="mt-2 flex gap-3">
                <input id={pwId} type="password" value={password} onChange={(e) => setPassword(e.target.value)} required
                  autoComplete="current-password" aria-invalid={error === 'Wrong operator password' || undefined}
                  className="flex-1 min-w-0 bg-ground border border-line rounded-xs px-3 h-10 text-base focus:border-muted outline-none" />
                {submit}
              </div>
            </>
          )}
          {!ready && !busy && <p className="mt-2 font-mono text-xs text-muted">{needsPassword ? 'Enter your name and password to start.' : 'Enter your name to start.'}</p>}
          {error && <p role="alert" className="mt-4 text-sm font-mono border border-line p-3 break-all">{error}</p>}
        </form>
      </div>
      {/* What the session is for: the same seven stops the case will walk through. */}
      <div className="lg:col-span-12"><Lifecycle /></div>
    </section>
  )
}
