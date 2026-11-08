import { Link, NavLink, useMatch } from 'react-router'
import { Emblem } from './Emblem'

/** One header for the whole site: same height, grid, labels and order on the story and in the console. */
export function SiteHeader({ onStory = false }: { onStory?: boolean }) {
  const inCase = useMatch('/cases/:id/*')
  const caseId = inCase?.params.id
  const inConsole = !!useMatch('/console') || !!caseId
  const tone = (on: boolean) => `navlink ${on ? 'text-ink' : 'text-muted'}`
  return (
    <header className="site-head">
      <div className="wrap h-16 flex items-center gap-3 sm:gap-6">
        <Link to="/" viewTransition className="brand min-h-11 flex items-center gap-2.5 whitespace-nowrap shrink-0 font-semibold tracking-[-0.01em]" aria-label="Body Double, home">
          <Emblem className="size-7" />
          <span>Body Double</span>
        </Link>
        {/* phone + case open: the wordmark stays; the breadcrumb scrolls sideways if it runs out of room */}
        <nav aria-label="Primary" className="ml-auto flex items-center gap-1 text-sm whitespace-nowrap min-w-0 overflow-x-auto">
          {onStory
            ? <a className="navlink text-muted hidden sm:inline-block" href="#how">How it works</a>
            : <Link to="/#how" viewTransition className="navlink text-muted hidden sm:inline-block">How it works</Link>}
          <Link to="/console" viewTransition className={tone(inConsole)} aria-current={inConsole && !caseId ? 'page' : undefined}>Console</Link>
          {caseId && (
            <>
              <span className="text-muted" aria-hidden="true">/</span>
              <NavLink to={`/cases/${caseId}`} end className={({ isActive }) => `${tone(isActive)} font-mono`}>{caseId}</NavLink>
              <span className="text-muted" aria-hidden="true">/</span>
              <NavLink to={`/cases/${caseId}/evidence`} className={({ isActive }) => tone(isActive)}>Evidence</NavLink>
            </>
          )}
          {!caseId && (onStory
            ? <a className="btn btn-primary ml-2" href="#try">Try it</a>
            : <Link className="btn btn-primary ml-2" to="/#try" viewTransition>Try it</Link>)}
        </nav>
      </div>
    </header>
  )
}
