import { createBrowserRouter, Link, NavLink, Outlet, useMatch } from 'react-router'
import { Servers } from './routes/Servers'
import { CaseScreen } from './routes/Case'
import { CloseScreen } from './routes/Close'
import { NotFound } from './routes/NotFound'

function Shell() {
  const inCase = useMatch('/cases/:id/*')
  const caseId = inCase?.params.id
  return (
    <div className="min-h-dvh flex flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:left-4 focus:top-3 focus:z-50 btn">Skip to content</a>
      <header className="border-b border-line">
        <div className="mx-auto max-w-[1600px] px-4 md:px-6 h-14 flex items-center gap-6">
          <Link to="/" className="flex items-center gap-2.5 font-semibold tracking-[-0.01em]" aria-label="Body Double, servers">
            <svg width="22" height="16" viewBox="0 0 22 16" aria-hidden="true">
              <rect x="1" y="1" width="9" height="14" rx="1" fill="none" stroke="currentColor" strokeWidth="1.5" />
              <rect x="12" y="1" width="9" height="14" rx="1" fill="none" stroke="var(--color-agent)" strokeWidth="1.5" />
            </svg>
            Body Double
          </Link>
          <nav aria-label="Primary" className="flex items-center gap-1 text-sm">
            <NavLink to="/" end className={({ isActive }) => `navlink ${isActive ? 'text-ink' : 'text-muted'}`}>
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
  {
    element: <Shell />,
    children: [
      { path: '/', element: <Servers /> },
      { path: '/cases/:id', element: <CaseScreen /> },
      { path: '/cases/:id/evidence', element: <CloseScreen /> },
      { path: '*', element: <NotFound /> },
    ],
  },
])
