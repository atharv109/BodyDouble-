import { createBrowserRouter, Link, NavLink, Outlet, useMatch } from 'react-router'
import { Servers } from './routes/Servers'
import { CaseScreen } from './routes/Case'
import { CloseScreen } from './routes/Close'
import { NotFound } from './routes/NotFound'
import { OperatorGate } from './ui/OperatorGate'
import { Story } from './story/Story'
import { Emblem } from './ui/Emblem'

function Shell() {
  const inCase = useMatch('/cases/:id/*')
  const caseId = inCase?.params.id
  return (
    <div className="min-h-dvh flex flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:inset-x-0 focus:top-0 focus:h-14 focus:z-50 focus:justify-center btn skip">Skip to content</a>
      <header className="border-b border-line" style={{ viewTransitionName: 'site-head' }}>
        <div className="mx-auto max-w-[1600px] px-4 md:px-6 h-14 flex items-center gap-3 sm:gap-6">
          <Link to="/" viewTransition className="brand min-h-11 flex items-center gap-2.5 whitespace-nowrap shrink-0 font-semibold tracking-[-0.01em]" aria-label="Body Double, home">
            <Emblem className="size-7" />
            <span>Body Double</span>
          </Link>
          {/* phone + case open: the wordmark stays; the breadcrumb scrolls sideways if it runs out of room */}
          <nav aria-label="Primary" className="flex items-center gap-1 text-sm whitespace-nowrap min-w-0 overflow-x-auto">

            <NavLink to="/console" end viewTransition className={({ isActive }) => `navlink ${isActive ? 'text-ink' : 'text-muted'}`}>
              Servers
            </NavLink>
            {caseId && (
              <>
                <span className="text-line" aria-hidden="true">/</span>
                <NavLink to={`/cases/${caseId}`} end className={({ isActive }) => `navlink font-mono ${isActive ? 'text-ink' : 'text-muted'}`}>
                  {caseId}
                </NavLink>
                <span className="text-line" aria-hidden="true">/</span>
                <NavLink to={`/cases/${caseId}/evidence`} className={({ isActive }) => `navlink ${isActive ? 'text-ink' : 'text-muted'}`}>
                  Evidence
                </NavLink>
              </>
            )}
          </nav>
        </div>
      </header>
      <main id="main" className="flex-1 flex flex-col">
        <Outlet />
      </main>
    </div>
  )
}

export const router = createBrowserRouter([
  { path: '/', element: <Story /> },
  {
    element: <Shell />,
    children: [
      {
        element: <OperatorGate><Outlet /></OperatorGate>,
        children: [
          { path: '/console', element: <Servers /> },
          { path: '/cases/:id', element: <CaseScreen /> },
          { path: '/cases/:id/evidence', element: <CloseScreen /> },
        ],
      },
      { path: '*', element: <NotFound /> },
    ],
  },
])
