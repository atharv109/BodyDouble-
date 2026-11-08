import { useLayoutEffect, type RefObject } from 'react'
import { gsap } from 'gsap'
import { ScrollTrigger } from 'gsap/ScrollTrigger'
import Lenis from 'lenis'
import { PEEL_END } from './Peel'

gsap.registerPlugin(ScrollTrigger)

export const reducedMotion = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches
const LATCH = 'power3.out' // close to cubic-bezier(.2,.8,.2,1): fast out, hard stop

/**
 * Everything that moves on the story page, on one clock (gsap.ticker), reverted on unmount.
 * - Lenis smooth scroll (off under reduced motion).
 * - The peel: plays once on load; reduced motion gets its end pose as a still.
 * - Idle: a scan line passing over the twin only, while the hero is on screen.
 * - Reveals: [data-reveal] latch in from 8 px below, once.
 * - The crossing: [data-crossing] toggles onCrossing(true/false) as the approve stop passes mid-screen.
 * - The rail index: onStep(k) names the stop crossing mid-screen (-1 above the case).
 * - A /#how or /#try deep link (from the console) lands on its section once the page is laid out.
 */
export function useStoryMotion(root: RefObject<HTMLElement | null>, onCrossing: (on: boolean) => void, onStep: (k: number) => void) {
  useLayoutEffect(() => {
    const el = root.current
    if (!el) return
    const rm = reducedMotion()
    let lenis: Lenis | null = null
    let raf: ((t: number) => void) | null = null
    // smooth scroll on desktop only: phones keep native touch scrolling, which is smoother and cheaper there
    if (!rm && matchMedia('(min-width: 1024px) and (pointer: fine)').matches) {
      lenis = new Lenis({ anchors: { offset: -72 }, lerp: 0.12 })
      lenis.on('scroll', ScrollTrigger.update)
      raf = (t: number) => lenis!.raf(t * 1000)
      gsap.ticker.add(raf)
      gsap.ticker.lagSmoothing(0)
    }

    const ctx = gsap.context(() => {
      const q = (name: string) => el.querySelector(`[data-peel="${name}"]`)
      const hero = el.querySelector('[data-hero]')
      const end = (tl: gsap.core.Timeline | typeof gsap) => {
        tl.to(q('glass'), { attr: PEEL_END.glass, stroke: 'var(--color-frame)', duration: 1, ease: 'power3.inOut' }, 0)
        tl.to(q('original'), { ...PEEL_END.original, duration: 1, ease: 'power3.inOut' }, 0)
        tl.to(q('twin'), { ...PEEL_END.twin, duration: 1, ease: 'power3.inOut' }, 0)
        tl.to([q('snapshot'), q('snapshot-label')], { opacity: 1, duration: 0.3, ease: 'none' }, 0.35)
        tl.set(q('seal'), { opacity: 1 }, 0.65)
        tl.to(q('seal'), { attr: { 'stroke-dashoffset': 0 }, duration: 0.35, ease: 'none' }, 0.65)
        tl.set(q('seal'), { attr: { 'stroke-dasharray': 'none' } }, 1) // drawn: drop the dash so no cap tick remains
        tl.to(q('labels'), { opacity: 1, duration: 0.2, ease: 'none' }, 0.8)
      }
      if (rm) {
        // The still frame is the finished peel: it tells the whole idea without motion.
        const tl = gsap.timeline({ paused: true }); end(tl); tl.progress(1)
      } else if (hero) {
        // The signature plays once on load (done well inside 2.5 s), so the first screen tells the idea.
        const tl = gsap.timeline({ delay: 0.6 })
        end(tl)
        tl.duration(1.7)

        // idle: the agent keeps reading the copy. Paused while the hero is off screen.
        const scan = q('scan')
        const tick = (t: number) => { gsap.set(scan, { y: (t * 7) % 25, opacity: 0.35 }) }
        ScrollTrigger.create({ trigger: hero, start: 'top bottom', end: 'bottom top',
          onToggle: (s) => (s.isActive ? gsap.ticker.add(tick) : (gsap.ticker.remove(tick), gsap.set(scan, { opacity: 0 }))) })
      }

      if (!rm) {
        el.dataset.motion = ''
        const all = (s: string, scope: Element = el) => gsap.utils.toArray<HTMLElement>(s, scope)
        const once = (trigger: Element, start = 'top 88%') => ({ trigger, start, once: true })

        // intro: the h1 lines rise out of their masks, then the copy, then the peel (above)
        gsap.from(all('[data-intro]'), { yPercent: 112, duration: 1.1, ease: 'power4.out', stagger: 0.09, delay: 0.05 })
        gsap.from(all('[data-intro-copy]'), { y: 10, opacity: 0, duration: 0.6, ease: LATCH, delay: 0.45 })

        all('[data-reveal]').forEach((n) => {
          gsap.from(n, { y: 8, opacity: 0, duration: 0.6, ease: LATCH, scrollTrigger: once(n, 'top 90%') })
        })
        // headings: word by word, in reading order
        all('[data-words]').forEach((h) => {
          gsap.from(all('.wi', h), { yPercent: 112, duration: 0.9, ease: 'power4.out', stagger: 0.035, scrollTrigger: once(h) })
        })

        // the twin's thread fills down the gutter with the reading
        const lane = el.querySelector('.lane-twin')
        const thread = el.querySelector('[data-thread]')
        if (lane && thread) gsap.fromTo(thread, { scaleY: 0 }, { scaleY: 1, ease: 'none',
          scrollTrigger: { trigger: lane, start: 'top 60%', end: 'bottom 60%', scrub: 0.4, invalidateOnRefresh: true } })

        // the two bad options arrive from opposite sides (scrubbed on desktop; phones get a one-shot latch, cheaper per frame)
        const wide = matchMedia('(min-width: 1024px)').matches
        all('[data-side]').forEach((o) => {
          const x = o.dataset.side === 'l' ? -56 : 56
          if (wide) gsap.from(o, { x, opacity: 0, ease: 'none', scrollTrigger: { trigger: o, start: 'top 92%', end: 'top 55%', scrub: 0.5 } })
          else gsap.from(o, { y: 16, opacity: 0, duration: 0.6, ease: LATCH, scrollTrigger: once(o, 'top 90%') })
        })
        // the three moves latch in one after another
        const moves = all('[data-move]')
        if (moves.length) gsap.from(moves, { y: 18, opacity: 0, duration: 0.6, ease: LATCH, stagger: 0.12, scrollTrigger: once(moves[0]) })

        // evidence types itself in as its stop (or the note) reaches mid-screen
        all('[data-type]').forEach((t) => {
          ScrollTrigger.create({ trigger: t, start: 'top 85%', once: true, onEnter: () => { t.dataset.typed = '' } })
        })

        // the walls close in around the agent, outermost first, scrubbed
        const walls = el.querySelector('[data-walls]')
        if (walls) {
          const tl = gsap.timeline({ scrollTrigger: { trigger: walls, start: 'top 95%', end: 'top 40%', scrub: 0.6 } })
          all('.wall', walls).forEach((w, k) => tl.from(w, { scale: 1.06, opacity: 0, ease: 'power2.out', duration: 1 }, k * 0.4))
          tl.from(walls.querySelector('.walls-core'), { opacity: 0, scale: 0.9, duration: 0.6 }, 0.9)
        }

        // zeros drop into place
        const zeros = all('[data-zero]')
        if (zeros.length) {
          gsap.from(zeros.map((z) => z.querySelector('.line > span')), { yPercent: -110, duration: 0.9, ease: 'power4.out', stagger: 0.14, scrollTrigger: once(zeros[0]) })
          gsap.from(zeros.map((z) => z.querySelector('dt')), { opacity: 0, y: 8, duration: 0.6, ease: LATCH, stagger: 0.14, delay: 0.3, scrollTrigger: once(zeros[0]) })
        }

        // the Vultr rows and the attacks draw in, row by row
        for (const sel of ['[data-row]', '.attack']) {
          const rows = all(sel)
          if (!rows.length) continue
          gsap.set(rows, { opacity: 0, x: -14 })
          ScrollTrigger.batch(rows, { start: 'top 92%', once: true,
            onEnter: (b) => gsap.to(b, { opacity: 1, x: 0, duration: 0.5, ease: LATCH, stagger: 0.05, overwrite: true }) })
        }
      }

      const cross = el.querySelector<HTMLElement>('[data-crossing]')
      if (cross) {
        ScrollTrigger.create({ trigger: cross, start: 'top 55%',
          onEnter: () => onCrossing(true), onLeaveBack: () => onCrossing(false) })
      }

      gsap.utils.toArray<HTMLElement>('[data-stop]', el).forEach((n, k) => {
        ScrollTrigger.create({ trigger: n, start: 'top 55%', end: 'bottom 55%',
          onToggle: (s) => { if (s.isActive) onStep(k) },
          ...(k === 0 ? { onLeaveBack: () => onStep(-1) } : {}) })
      })

      const target = location.hash.length > 1 ? el.querySelector<HTMLElement>(location.hash) : null
      if (target) gsap.delayedCall(0.05, () => {
        ScrollTrigger.refresh()
        if (lenis) lenis.scrollTo(target, { immediate: true, offset: -72 })
        else window.scrollTo(0, target.getBoundingClientRect().top + scrollY - 72)
      })
    }, el)

    return () => {
      ctx.revert()
      delete el.dataset.motion
      el.querySelectorAll<HTMLElement>('[data-typed]').forEach((t) => delete t.dataset.typed)
      if (raf) gsap.ticker.remove(raf)
      lenis?.destroy()
    }
    // onCrossing and onStep are stable setState wrappers
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
