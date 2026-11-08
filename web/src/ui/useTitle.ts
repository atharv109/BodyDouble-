import { useEffect } from 'react'

/** Unique document title per screen. */
export function useTitle(title: string) {
  useEffect(() => {
    document.title = title ? `${title} · Body Double` : 'Body Double'
  }, [title])
}
