import { useQuery } from '@tanstack/react-query'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

interface ActivityRow {
  id: string
  event_type: string
  timestamp: string
  who: string | null
  tier: string | null
  is_gift: boolean
  total: number | null
  bits: number | null
}

const TYPE_LABELS: Record<string, { label: string; className: string }> = {
  'channel.subscribe': { label: 'sub', className: 'bg-green-500/20 text-green-300' },
  'channel.subscription.gift': { label: 'gift', className: 'bg-pink-500/20 text-pink-300' },
  'channel.subscription.message': { label: 'resub', className: 'bg-sky-500/20 text-sky-300' },
  'channel.cheer': { label: 'cheer', className: 'bg-yellow-500/20 text-yellow-300' },
}

/**
 * Raw countable events, straight from EventSub — the "is it hitting?"
 * verification feed. No campaign math, no filtering: if Twitch sent
 * it, it's here, so discrepancies can be settled against ground truth.
 */
export function ActivityFeed({ channelSlug }: { channelSlug: string }) {
  const {
    data: rows = [],
    isError,
    isLoading,
  } = useQuery({
    queryKey: ['activity', channelSlug],
    queryFn: () => api<ActivityRow[]>(`/api/v1/events/channels/${channelSlug}/activity/`),
    retry: false,
    refetchInterval: 120_000, // slow backstop — SSE drives freshness
  })

  return (
    <details className="rounded border border-hive-border">
      <summary className="cursor-pointer px-3 py-2 text-xs text-hive-muted select-none">
        Recent activity (raw events)
      </summary>
      <div className="flex max-h-80 flex-col gap-0.5 overflow-y-auto border-t border-hive-border p-2">
        {isError && <p className="px-2 py-1 text-sm text-red-400">Couldn't load the event feed.</p>}
        {!isError && !isLoading && rows.length === 0 && (
          <p className="px-2 py-1 text-sm text-hive-muted">No countable events yet.</p>
        )}
        {rows.map((row) => (
          <ActivityLine key={row.id} row={row} />
        ))}
      </div>
    </details>
  )
}

function ActivityLine({ row }: { row: ActivityRow }) {
  const type = TYPE_LABELS[row.event_type] ?? {
    label: row.event_type,
    className: 'bg-hive-border text-hive-muted',
  }
  const tierNumber = row.tier ? Math.floor(Number.parseInt(row.tier, 10) / 1000) || 1 : null

  return (
    <div className="flex items-center gap-2 rounded px-2 py-1 text-sm hover:bg-hive-surface">
      <span className="w-24 shrink-0 font-mono text-xs text-hive-muted">
        {formatTimestamp(row.timestamp)}
      </span>
      <span
        className={cn(
          'w-12 shrink-0 rounded px-1.5 py-0.5 text-center text-xs font-medium',
          type.className,
        )}>
        {type.label}
      </span>
      <span className="truncate text-hive-text">{row.who ?? '—'}</span>
      {row.is_gift && row.event_type === 'channel.subscribe' && (
        <span className="text-xs text-hive-muted">(gift recipient — not counted)</span>
      )}
      <span className="ml-auto shrink-0 font-mono text-xs text-hive-muted">
        {row.event_type === 'channel.subscription.gift' && row.total != null && `×${row.total}`}
        {row.event_type === 'channel.cheer' && row.bits != null && `${row.bits} bits`}
        {tierNumber != null && tierNumber > 1 && ` T${tierNumber}`}
      </span>
    </div>
  )
}

function formatTimestamp(iso: string): string {
  return new Date(iso).toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  })
}
