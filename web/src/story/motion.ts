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
 */
export function useStoryMotion(root: RefObject<HTMLElement | null>, onCrossing: (on: boolean) => void) {
  useLayoutEffect(() => {
    const el = root.current
    if (!el) return
    const rm = reducedMotion()
    let lenis: Lenis | null = null
    let raf: ((t: number) => void) | null = null
    if (!rm) {
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
        tl.to(q('snapshot'), { opacity: 1, duration: 0.3, ease: 'none' }, 0.35)
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
        const tl = gsap.timeline({ delay: 0.35 })
        end(tl)
        tl.duration(1.7)

        // idle: the agent keeps reading the copy. Paused while the hero is off screen.
        const scan = q('scan')
        const tick = (t: number) => { gsap.set(scan, { y: (t * 7) % 25, opacity: 0.35 }) }
        ScrollTrigger.create({ trigger: hero, start: 'top bottom', end: 'bottom top',
          onToggle: (s) => (s.isActive ? gsap.ticker.add(tick) : (gsap.ticker.remove(tick), gsap.set(scan, { opacity: 0 }))) })
      }

      if (!rm) {
        gsap.utils.toArray<HTMLElement>('[data-reveal]', el).forEach((n) => {
          gsap.from(n, { y: 8, opacity: 0, duration: 0.6, ease: LATCH,
            scrollTrigger: { trigger: n, start: 'top 90%', once: true } })
        })
      }

      const cross = el.querySelector<HTMLElement>('[data-crossing]')
      if (cross) {
        ScrollTrigger.create({ trigger: cross, start: 'top 55%',
          onEnter: () => onCrossing(true), onLeaveBack: () => onCrossing(false) })
      }
    }, el)

    return () => {
      ctx.revert()
      if (raf) gsap.ticker.remove(raf)
      lenis?.destroy()
    }
    // onCrossing is a stable setState wrapper
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])
}
