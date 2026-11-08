import { useEffect } from 'react'

/** Unique document title per screen. */
export function useTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} · Body Double` : 'Body Double'
    // Canonical per route, set at runtime: a static tag in index.html makes vite try to bundle its href.
    let link = document.querySelector<HTMLLinkElement>('link[rel="canonical"]')
    if (!link) {
      link = document.createElement('link')
      link.rel = 'canonical'
      document.head.appendChild(link)
    }
    link.href = location.origin + location.pathname
  }, [title])
}
