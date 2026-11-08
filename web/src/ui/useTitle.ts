import { useEffect } from 'react'

/** Unique document title per screen. */
export function useTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} · Body Double` : 'Body Double'
    // Canonical per route (index.html ships one for "/"; this keeps it in step with client routing).
    const link = document.querySelector<HTMLLinkElement>('link[rel="canonical"]')
    if (link) link.href = location.origin + location.pathname
  }, [title])
}
