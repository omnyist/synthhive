import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

/**
 * Fetch helper for overlay widgets. Unlike `api()`, a failure never
 * redirects to login — a browser source that hits an error must fail
 * silent and invisible, not bounce OBS into an OAuth flow.
 */
export async function overlayApi<T>(path: string): Promise<T> {
  const res = await fetch(path, { credentials: 'omit' })
  if (!res.ok) throw new Error(`Request failed: ${res.status}`)
  return res.json()
}

/**
 * Subscribe to the channel's key-authed campaign SSE stream and
 * invalidate every overlay query when anything happens server-side.
 */
export function useOverlayStream(channelSlug: string, overlayKey: string) {
  const queryClient = useQueryClient()

  useEffect(() => {
    if (!overlayKey) return
    const source = new EventSource(
      `/api/v1/overlay/channels/${channelSlug}/stream?key=${overlayKey}`,
    )
    source.onmessage = () => {
      queryClient.invalidateQueries({ queryKey: ['overlay'] })
    }
    return () => source.close()
  }, [channelSlug, overlayKey, queryClient])
}

/**
 * Reload the widget when a deploy ships a new bundle. OBS browser
 * sources live for days — they keep executing the JavaScript they
 * loaded, no matter what the server ships later (Spoonee's goal
 * widget ran day-old math on fresh data). The SPA shell changes
 * content-hash references every build, so polling it and reloading
 * on change keeps long-lived widgets at most a few minutes stale.
 */
export function useAutoReload(intervalMs = 300_000) {
  useEffect(() => {
    let initialShell: string | null = null

    const check = async () => {
      try {
        const res = await fetch('/', { cache: 'no-store' })
        if (!res.ok) return
        const text = await res.text()
        if (initialShell === null) {
          initialShell = text
        } else if (text !== initialShell) {
          window.location.reload()
        }
      } catch {
        // Offline or mid-deploy — try again next tick.
      }
    }

    check()
    const id = setInterval(check, intervalMs)
    return () => clearInterval(id)
  }, [intervalMs])
}

/** Make the page transparent so OBS composites only the widget. */
export function useTransparentBody() {
  useEffect(() => {
    document.body.style.backgroundColor = 'transparent'
    return () => {
      document.body.style.backgroundColor = ''
    }
  }, [])
}
