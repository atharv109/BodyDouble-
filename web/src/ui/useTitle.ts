import { useEffect } from 'react'

export const SITE = (import.meta.env.VITE_SITE_URL ?? location.origin).replace(/\/$/, '')

/** Unique document title (and optionally description) per screen; canonical follows the route under VITE_SITE_URL. */
export function useTitle(title: string, description?: string) {
  useEffect(() => {
    document.title = title.startsWith('Body Double') ? title : title ? `${title} · Body Double` : 'Body Double'
    if (description) document.querySelector('meta[name="description"]')?.setAttribute('content', description)
    let link = document.querySelector<HTMLLinkElement>('link[rel="canonical"]')
    if (!link) {
      link = document.createElement('link')
      link.rel = 'canonical'
      document.head.appendChild(link)
    }
    link.href = SITE + location.pathname
  }, [title, description])
}
