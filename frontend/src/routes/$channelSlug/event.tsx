import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { BidWarSection } from '@/components/BidWarSection'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

interface Milestone {
  id: string
  threshold: number
  title: string
  description: string
  is_unlocked: boolean
  unlocked_at: string | null
  is_stretch: boolean
  goal_unit: string
}

interface Metric {
  total_subs: number
  total_resubs: number
  total_sub_points: number
  total_bits: number
}

interface Campaign {
  id: string
  name: string
  description: string
  start_date: string
  end_date: string
  metric: Metric
  milestones: Milestone[]
}

interface Gifter {
  display_name?: string
  username?: string
  total_count: number
}

export const Route = createFileRoute('/$channelSlug/event')({
  component: EventPage,
})

function EventPage() {
  const { channelSlug } = Route.useParams()
  const [error, setError] = useState<string | null>(null)

  const { data: campaign, isLoading } = useQuery({
    queryKey: ['campaign', channelSlug],
    queryFn: () => api<Campaign | null>(`/api/v1/campaign/channels/${channelSlug}/`),
    retry: false,
  })

  const { data: gifters = [] } = useQuery({
    queryKey: ['gifters', channelSlug],
    queryFn: () => api<Gifter[]>(`/api/v1/campaign/channels/${channelSlug}/gifters/`),
    retry: false,
    enabled: !!campaign,
  })

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8">
        <p className="text-hive-muted">Loading event...</p>
      </div>
    )
  }

  if (!campaign) {
    return (
      <div className="flex flex-1 flex-col items-center justify-center gap-2 p-8">
        <p className="text-sm text-hive-text">No active event.</p>
        <p className="text-xs text-hive-muted">
          Campaigns are created in the admin — once one is active, everything for it lives here.
        </p>
      </div>
    )
  }

  const metric = campaign.metric
  const dateRange = `${formatDate(campaign.start_date)} – ${formatDate(campaign.end_date)}`

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-4">
      <div>
        <div className="flex items-baseline gap-3">
          <h2 className="text-lg font-semibold text-hive-text">{campaign.name}</h2>
          <span className="text-xs text-hive-muted">{dateRange}</span>
        </div>
        {campaign.description && (
          <p className="mt-0.5 text-xs text-hive-muted">{campaign.description}</p>
        )}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Subs" value={metric.total_subs} />
        <StatTile label="Resubs" value={metric.total_resubs} />
        <StatTile label="Sub points" value={metric.total_sub_points} />
        <StatTile label="Bits" value={metric.total_bits} />
      </div>

      <MilestoneBoard milestones={campaign.milestones} metric={metric} />

      {error && <p className="text-sm text-red-400">{error}</p>}

      <BidWarSection channelSlug={channelSlug} onError={setError} />

      {gifters.length > 0 && (
        <div className="flex flex-col gap-1">
          <h3 className="text-xs font-medium tracking-wide text-hive-muted uppercase">
            Top gifters
          </h3>
          {gifters.map((g, i) => (
            <div
              key={g.username ?? g.display_name ?? i}
              className="flex items-center gap-3 rounded px-3 py-1.5 text-sm hover:bg-hive-surface">
              <span className="w-5 text-right font-mono text-xs text-hive-muted">{i + 1}.</span>
              <span className="text-hive-text">{g.display_name ?? g.username}</span>
              <span className="ml-auto font-mono text-hive-muted">{g.total_count}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function StatTile({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col gap-1 rounded-lg border border-hive-border bg-hive-surface p-3">
      <span className="text-xs text-hive-muted">{label}</span>
      <span className="font-mono text-2xl font-bold text-hive-text">{value.toLocaleString()}</span>
    </div>
  )
}

function MilestoneBoard({ milestones, metric }: { milestones: Milestone[]; metric: Metric }) {
  if (milestones.length === 0) return null

  const nextId =
    milestones.find((m) => !m.is_unlocked && !m.is_stretch)?.id ??
    milestones.find((m) => !m.is_unlocked)?.id ??
    null

  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-xs font-medium tracking-wide text-hive-muted uppercase">Goals</h3>
      {milestones.map((m) => {
        const isPoints = m.goal_unit === 'sub_points'
        const current = isPoints ? metric.total_sub_points : metric.total_subs + metric.total_resubs
        const pct = m.is_unlocked ? 100 : Math.min(100, Math.floor((current / m.threshold) * 100))
        const isNext = m.id === nextId

        return (
          <div
            key={m.id}
            className={cn(
              'flex flex-col gap-1.5 rounded border px-3 py-2',
              m.is_unlocked
                ? 'border-green-500/30 bg-green-500/5'
                : isNext
                  ? 'border-hive-accent bg-hive-accent-dim/10'
                  : 'border-hive-border bg-hive-surface',
            )}>
            <div className="flex items-center gap-2 text-sm">
              <span className={cn(m.is_unlocked ? 'text-green-300' : 'text-hive-muted')}>
                {m.is_unlocked ? '✓' : '○'}
              </span>
              <span className="font-medium text-hive-text">{m.title}</span>
              {m.is_stretch && (
                <span className="rounded bg-yellow-500/20 px-1.5 py-0.5 text-xs text-yellow-300">
                  stretch
                </span>
              )}
              {isNext && <span className="text-xs text-hive-accent">next</span>}
              <span className="ml-auto font-mono text-xs text-hive-muted">
                {current.toLocaleString()} / {m.threshold.toLocaleString()}
                {isPoints ? ' pts' : ''}
              </span>
            </div>
            <div className="h-1 overflow-hidden rounded-full bg-hive-border">
              <div
                className={cn(
                  'h-full rounded-full',
                  m.is_unlocked ? 'bg-green-400' : 'bg-hive-accent-dim',
                )}
                style={{ width: `${pct}%` }}
              />
            </div>
          </div>
        )
      })}
    </div>
  )
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' })
}
