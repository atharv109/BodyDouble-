import { createBrowserRouter, Outlet } from 'react-router'
import { Servers } from './routes/Servers'
import { CaseScreen } from './routes/Case'
import { CloseScreen } from './routes/Close'
import { NotFound } from './routes/NotFound'
import { OperatorGate } from './ui/OperatorGate'
import { Story } from './story/Story'
import { SiteHeader } from './ui/SiteHeader'

function Shell() {
  return (
    <div className="min-h-dvh flex flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:fixed focus:inset-x-0 focus:top-0 focus:h-14 focus:z-50 focus:justify-center btn skip">Skip to content</a>
      <SiteHeader />
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
