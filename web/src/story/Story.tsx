import { useCallback, useRef, useState } from 'react'
import { Link } from 'react-router'
import { Emblem } from '../ui/Emblem'
import { useTitle } from '../ui/useTitle'
import { Peel } from './Peel'
import { useStoryMotion } from './motion'
import { TryIt } from './TryIt'
import { blast, hero, how, note, problem, prod, tryIt, vultr, walls, whyCopy, type Incident } from './content'
import './story.css'

export function Story() {
  useTitle('Body Double: investigate a hacked Vultr server on its sealed twin',
    'Body Double snapshots a suspect Vultr server, investigates an exact copy in a sealed room, and proposes containment a human approves. Production keeps running.')
  const root = useRef<HTMLDivElement>(null)
  const [contained, setContained] = useState(false)
  const onCrossing = useCallback((on: boolean) => setContained(on), [])
  useStoryMotion(root, onCrossing)

  return (
    <div ref={root} className="story" data-contained={contained || undefined}>
      <a href="#main" className="btn skip sr-only focus:not-sr-only focus:fixed focus:inset-x-0 focus:top-0 focus:h-14 focus:z-50 focus:justify-center">Skip to content</a>
      <header className="story-head">
        <div className="wrap h-16 flex items-center gap-4">
          <Link to="/" className="brand min-h-11 flex items-center gap-2.5 font-semibold tracking-[-0.01em]" aria-label="Body Double, home">
            <Emblem className="size-7" />
            <span>Body Double</span>
          </Link>
          <nav aria-label="Primary" className="ml-auto flex items-center gap-1 text-sm">
            <a className="navlink text-muted hidden sm:inline-block" href="#how">How it works</a>
            <Link className="navlink text-muted" to="/console" viewTransition>Console</Link>
            <a className="btn btn-primary ml-2" href="#try">Try it</a>
          </nav>
        </div>
      </header>

      <main id="main" data-testid="story">
        {/* beat 1: what it is. The hero stage holds the peel while the hero scrolls. */}
        <section data-testid="beat-1" aria-labelledby="b1" className="hero" data-hero>
          <div className="hero-stage wrap">
            <h1 className="display hero-h1">
              <span>{hero.h1[0]}</span> <span>{hero.h1[1]}</span>
            </h1>
            <div className="hero-copy">
              <h2 id="b1" className="t-m font-medium">{hero.h2}</h2>
              <p className="mt-3 text-muted">{hero.lede}</p>
              <div className="mt-6 flex flex-wrap gap-3">
                <a className="btn btn-agent btn-lg" href="#try">Try a live case</a>
                <a className="btn btn-lg" href="#how">How it works</a>
              </div>
            </div>
            <div className="hero-peel"><Peel /></div>
          </div>
        </section>

        <div className="lanes wrap">
          <aside className="lane-prod" aria-label="Production server">
            <ProdCard contained={contained} />
          </aside>

          <div className="lane-twin">
            {/* beat 2: the problem */}
            <section data-testid="beat-2" aria-labelledby="b2" className="beat">
              <h2 id="b2" className="display-2" data-reveal>{problem.h2}</h2>
              <p className="lede" data-reveal>{problem.lede}</p>
              <div className="options">
                {problem.options.map((o) => (
                  <article key={o.title} className="option" data-reveal>
                    <h3 className="t-m font-semibold">{o.title}</h3>
                    <p className="mt-2 text-muted">{o.cost}</p>
                    <ul className="incidents">{o.incidents.map((i) => <IncidentRow key={i.name} i={i} />)}</ul>
                  </article>
                ))}
              </div>
              <p className="coda" data-reveal>{problem.coda}</p>
            </section>

            {/* beat 3: why a copy, and why it never boots */}
            <section data-testid="beat-3" aria-labelledby="b3" className="beat">
              <h2 id="b3" className="display-2" data-reveal>{whyCopy.h2}</h2>
              <p className="lede" data-reveal>{whyCopy.lede}</p>
              <figure className="evidence-quote" data-reveal>
                <ul className="incidents"><IncidentRow i={whyCopy.incident} /></ul>
                <figcaption className="mt-3 font-medium">{whyCopy.incidentPoint}</figcaption>
              </figure>
              <ol className="moves">
                {whyCopy.moves.map((m, k) => (
                  <li key={m.title} data-reveal>
                    <span className="move-n" aria-hidden="true">{k + 1}</span>
                    <h3 className="font-semibold">{m.title}</h3>
                    <p className="text-muted mt-1">{m.text}</p>
                    {m.code && <code className="artifact mt-3">{m.code}</code>}
                  </li>
                ))}
              </ol>
            </section>

            {/* beat 4: how it works, the recorded case */}
            <section id="how" data-testid="beat-4" aria-labelledby="b4" className="beat">
              <h2 id="b4" className="display-2" data-reveal>{how.h2}</h2>
              <p className="lede" data-reveal>{how.lede}</p>
              <ol className="stops">
                {how.stops.map((s, k) => (
                  <li key={s.state} className="stop" data-reveal data-crossing={s.crossing || undefined}>
                    <div className="stop-head">
                      <span className="stop-n">{k + 1}</span>
                      <span className="stop-state">{s.state}</span>
                    </div>
                    <div>
                      <h3 className="t-m font-semibold">{s.title}</h3>
                      <p className="mt-1 text-muted max-w-[56ch]">{s.text}</p>
                      <div className="mt-3 grid gap-1.5">
                        {s.artifacts.map((a) => <code key={a.text} className={`artifact ${a.tone ? `artifact--${a.tone}` : ''}`}>{a.text}</code>)}
                      </div>
                    </div>
                    {s.crossing && <span className="crossing" aria-hidden="true" />}
                  </li>
                ))}
              </ol>
            </section>

            {/* beat 5: three walls, nested outermost to innermost */}
            <section data-testid="beat-5" aria-labelledby="b5" className="beat">
              <h2 id="b5" className="display-2" data-reveal>{walls.h2}</h2>
              <p className="lede" data-reveal>{walls.lede}</p>
              <div className="walls" data-reveal>
                <Wall n={1} {...walls.items[0]}>
                  <Wall n={2} {...walls.items[1]}>
                    <Wall n={3} {...walls.items[2]}>
                      <p className="walls-core">the agent</p>
                    </Wall>
                  </Wall>
                </Wall>
              </div>
            </section>

            {/* beat 6: the attacker's note */}
            <section data-testid="beat-6" aria-labelledby="b6" className="beat">
              <h2 id="b6" className="display-2" data-reveal>{note.h2}</h2>
              <figure className="note" data-reveal>
                <div className="note-meta">
                  <span className="sev">high</span>
                  <span>injection flagged</span>
                  <span className="note-path">{note.path}</span>
                  <span>sha256 {note.sha}</span>
                </div>
                <blockquote className="note-quote">“{note.quote}”</blockquote>
                <figcaption className="note-verdict">Reported as evidence. Not followed.</figcaption>
              </figure>
              <p className="lede" data-reveal>{note.text}</p>
            </section>

            {/* beat 7: blast radius zero */}
            <section data-testid="beat-7" aria-labelledby="b7" className="beat">
              <h2 id="b7" className="display-2" data-reveal>{blast.h2}</h2>
              <dl className="zeros">
                {blast.zeros.map((z) => (
                  <div key={z} data-reveal><dt>{z}</dt><dd>0</dd></div>
                ))}
              </dl>
              <p className="text-muted mt-6" data-reveal>{blast.lede}</p>
            </section>

            {/* beat 8: built on Vultr */}
            <section data-testid="beat-8" aria-labelledby="b8" className="beat">
              <h2 id="b8" className="display-2" data-reveal>{vultr.h2}</h2>
              <p className="lede" data-reveal>{vultr.lede}</p>
              <table className="services" data-reveal>
                <caption className="sr-only">Vultr services and their role in Body Double</caption>
                <thead className="sr-only"><tr><th scope="col">Service</th><th scope="col">Role</th></tr></thead>
                <tbody>
                  {vultr.services.map(([s, r]) => (
                    <tr key={s}><th scope="row">{s}</th><td>{r}</td></tr>
                  ))}
                </tbody>
              </table>
            </section>

            {/* beat 9: try it */}
            <section id="try" data-testid="beat-9" aria-labelledby="b9" className="beat beat-final">
              <h2 id="b9" className="display">{tryIt.h2}</h2>
              <p className="lede">{tryIt.text}</p>
              <TryIt label={tryIt.button} />
            </section>
          </div>
        </div>
      </main>

      <footer className="story-foot wrap">
        <Link to="/" className="brand flex items-center gap-2.5 font-semibold min-h-11" aria-label="Body Double, home"><Emblem className="size-6" />Body Double</Link>
        <p className="text-muted text-sm">Built during Vultr Agent Rush, Nov 3 to 8 2026. MIT licence. Set in IBM Plex.</p>
        <Link to="/console" viewTransition className="navlink text-muted text-sm">Console</Link>
      </footer>
    </div>
  )
}

function ProdCard({ contained }: { contained: boolean }) {
  return (
    <div className="prod-card" data-state={contained ? 'contained' : 'untouched'}>
      <p className="label">Production</p>
      <p className="prod-name font-mono">{prod.label}</p>
      <dl className="prod-facts">
        <div className="prod-addr"><dt className="sr-only">Address</dt><dd className="font-mono">{prod.ip} · {prod.region}</dd></div>
        <div className="prod-state"><dt>State</dt><dd>running</dd></div>
        <div className="prod-fw"><dt>Firewall</dt><dd className="font-mono">{contained ? `${prod.firewallAfter} (quarantine)` : prod.firewallBefore}</dd></div>
        <div><dt>Writes before approval</dt><dd className="font-mono">0</dd></div>
      </dl>
      <p className="prod-note">{contained ? 'Changed once, by the approved action.' : 'Demo server. Nothing here changes until a human approves.'}</p>
    </div>
  )
}

function IncidentRow({ i }: { i: Incident }) {
  return (
    <li className="incident">
      <p><span className="font-semibold">{i.name}</span> <span className="text-muted font-mono text-xs">{i.when}</span></p>
      <p className="mt-1 text-muted">{i.text}</p>
      <p className="mt-1 flex flex-wrap gap-x-4">
        {i.sources.map((s) => (
          <a key={s.href} className="source" href={s.href} target="_blank" rel="noopener noreferrer">
            {s.label}<span className="arrow" aria-hidden="true">↗</span><span className="sr-only"> (opens in a new tab)</span>
          </a>
        ))}
      </p>
    </li>
  )
}

function Wall({ n, title, text, children }: { n: number; title: string; text: string; children: React.ReactNode }) {
  return (
    <div className={`wall wall-${n}`}>
      <h3 className="font-semibold"><span className="wall-n">Wall {n}.</span> {title}</h3>
      <p className="text-muted mt-1 max-w-[52ch]">{text}</p>
      <div className="wall-inner">{children}</div>
    </div>
  )
}
