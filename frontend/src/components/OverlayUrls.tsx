import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '@/lib/api'

interface OverlayUrlsResponse {
  overlay_key: string
  widgets: { name: string; path: string }[]
}

/** OBS browser-source URLs for the channel's overlay widgets. */
export function OverlayUrls({ channelSlug }: { channelSlug: string }) {
  const { data } = useQuery({
    queryKey: ['overlay-urls', channelSlug],
    queryFn: () => api<OverlayUrlsResponse>(`/api/v1/overlay/channels/${channelSlug}/urls/`),
    retry: false,
    staleTime: Infinity,
  })

  if (!data) return null

  return (
    <details className="rounded border border-hive-border">
      <summary className="cursor-pointer px-3 py-2 text-xs text-hive-muted select-none">
        Overlay widgets (OBS browser sources)
      </summary>
      <div className="flex flex-col gap-1.5 border-t border-hive-border p-3">
        <p className="text-xs text-hive-muted">
          Add each as a browser source in OBS. The key is a secret — anyone with the URL can read
          the widget data.
        </p>
        {data.widgets.map((w) => (
          <WidgetUrlRow key={w.path} name={w.name} url={`${window.location.origin}${w.path}`} />
        ))}
      </div>
    </details>
  )
}

function WidgetUrlRow({ name, url }: { name: string; url: string }) {
  const [copied, setCopied] = useState(false)

  const copy = () => {
    navigator.clipboard.writeText(url).then(() => {
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    })
  }

  return (
    <div className="flex items-center gap-2">
      <span className="w-16 shrink-0 text-xs text-hive-text">{name}</span>
      <code className="min-w-0 flex-1 truncate rounded bg-hive-dark px-2 py-1 font-mono text-xs text-hive-muted">
        {url}
      </code>
      <button
        type="button"
        onClick={copy}
        className="shrink-0 rounded border border-hive-border px-2 py-1 text-xs text-hive-muted transition-colors hover:text-hive-text">
        {copied ? 'Copied!' : 'Copy'}
      </button>
    </div>
  )
}
