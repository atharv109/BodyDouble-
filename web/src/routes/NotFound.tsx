import { Link } from 'react-router'
import { useTitle } from '../ui/useTitle'

/** 404 in the site's own terms: a sealed frame with no twin in it. */
export function NotFound() {
  useTitle('Page not found', 'There is no page at this address. Go back to the story or to the console.')
  return (
    <section className="mx-auto max-w-[1600px] w-full px-4 md:px-6 py-16 md:py-24 grid md:grid-cols-12 gap-x-6 gap-y-10 items-center">
      <div className="md:col-span-7">
        <p className="label">404 · no such path</p>
        <h1 className="mt-4 text-[2.6rem] md:text-[4.5rem] xl:text-[6rem] leading-[0.95] font-semibold tracking-[-0.045em] -ml-[0.05em]">Page not found.</h1>
        <p className="mt-5 text-muted max-w-[44ch] text-[17px] leading-[1.55]">There is nothing at this address to snapshot. Unlike a server, a missing page is not a finding.</p>
        <div className="mt-8 flex flex-wrap gap-3">
          <Link to="/" viewTransition className="btn btn-primary h-11">Back to the story</Link>
          <Link to="/console" viewTransition className="btn h-11">Open the console</Link>
        </div>
      </div>
      {/* the seal frame, drawn shut around nothing */}
      <svg viewBox="0 0 64 64" className="md:col-span-4 md:col-start-9 w-40 md:w-full max-w-[22rem]" aria-hidden="true">
        <rect x="8" y="8" width="48" height="48" rx="10" fill="none" stroke="var(--color-agent)" strokeWidth="1.6" />
        <rect x="20" y="20" width="24" height="24" rx="4.5" fill="none" stroke="var(--color-line)" strokeWidth="1.2" strokeDasharray="2 2" />
        <text x="32" y="61.5" textAnchor="middle" fontFamily="var(--font-mono)" fontSize="3.2" fill="var(--color-muted)">twin · empty</text>
      </svg>
    </section>
  )
}
