import { Link } from 'react-router'

export function NotFound() {
  return (
    <section className="mx-auto max-w-[1600px] w-full px-4 md:px-6 py-24 grid md:grid-cols-12 gap-6">
      <p className="label md:col-span-3">404 · no such record</p>
      <div className="md:col-span-6">
        <h1 className="text-4xl md:text-5xl font-semibold tracking-[-0.02em]">Nothing was found here.</h1>
        <p className="mt-4 text-muted max-w-prose">Unlike a server, a missing page isn't a finding. Go back to your servers and pick one to investigate.</p>
        <Link to="/console" className="btn btn-primary mt-8">Back to servers</Link>
      </div>
    </section>
  )
}
