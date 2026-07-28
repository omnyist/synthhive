import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { BidWarSection } from '@/components/BidWarSection'
import type { Campaign, CampaignSummary, Metric, Milestone } from '@/components/EventEditor'
import { EventEditor } from '@/components/EventEditor'
import { api } from '@/lib/api'
import { useCampaignStream } from '@/lib/useCampaignStream'
import { cn } from '@/lib/utils'

interface Gifter {
  display_name?: string
  username?: string
  total_count: number
}

export const Route = createFileRoute('/$channelSlug/event')({
  component: EventPage,
  validateSearch: (search: Record<string, unknown>): { campaign?: string } => ({
    campaign: typeof search.campaign === 'string' ? search.campaign : undefined,
  }),
})

function EventPage() {
  const { channelSlug } = Route.useParams()
  const { campaign: selectedId } = Route.useSearch()
  const navigate = Route.useNavigate()
  const [error, setError] = useState<string | null>(null)
  const [mode, setMode] = useState<'view' | 'create' | 'edit'>('view')

  useCampaignStream(channelSlug)

  const { data: campaigns = [], isLoading: listLoading } = useQuery({
    queryKey: ['campaigns', channelSlug],
    queryFn: () => api<CampaignSummary[]>(`/api/v1/campaigns/channels/${channelSlug}/`),
    retry: false,
  })

  const activeId = campaigns.find((c) => c.is_active)?.id ?? null
  const viewingId = selectedId ?? activeId

  const { data: campaign, isLoading: detailLoading } = useQuery({
    queryKey: ['campaign', channelSlug, viewingId],
    queryFn: () => api<Campaign>(`/api/v1/campaigns/channels/${channelSlug}/${viewingId}/`),
    retry: false,
    enabled: !!viewingId,
  })

  const { data: gifters = [] } = useQuery({
    queryKey: ['gifters', channelSlug, viewingId],
    queryFn: () =>
      api<Gifter[]>(`/api/v1/campaign/channels/${channelSlug}/gifters/?campaign_id=${viewingId}`),
    retry: false,
    enabled: !!viewingId,
  })

  const selectCampaign = (id: string) => {
    setMode('view')
    navigate({ search: { campaign: id === activeId ? undefined : id } })
  }

  if (listLoading || (viewingId && detailLoading && !campaign)) {
    return (
      <div className="flex items-center justify-center p-8">
        <p className="text-hive-muted">Loading event...</p>
      </div>
    )
  }

  const isPast = !!campaign && !campaign.is_active

  const header = (
    <div className="flex items-center gap-2">
      {campaigns.length > 0 && (
        <select
          value={viewingId ?? ''}
          onChange={(e) => e.target.value && selectCampaign(e.target.value)}
          className="rounded border border-hive-border bg-hive-dark px-2 py-1 text-xs text-hive-text focus:border-hive-accent focus:outline-none">
          {!viewingId && <option value="">Pick an event…</option>}
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
              {c.is_active ? ' (active)' : ''}
            </option>
          ))}
        </select>
      )}
      <div className="ml-auto flex gap-1.5">
        {campaign && mode === 'view' && (
          <button
            type="button"
            onClick={() => setMode('edit')}
            className="rounded border border-hive-border px-2.5 py-1 text-xs text-hive-muted transition-colors hover:text-hive-text">
            Edit
          </button>
        )}
        {mode === 'view' && (
          <button
            type="button"
            onClick={() => setMode('create')}
            className="rounded bg-hive-accent-dim px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-hive-accent-dim/80">
            New event
          </button>
        )}
      </div>
    </div>
  )

  if (mode !== 'view') {
    return (
      <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
        {header}
        <EventEditor
          channelSlug={channelSlug}
          campaign={mode === 'edit' ? (campaign ?? null) : null}
          onClose={() => setMode('view')}
          onSaved={(id) => {
            setMode('view')
            navigate({ search: { campaign: id === activeId ? undefined : id } })
          }}
        />
      </div>
    )
  }

  if (!campaign) {
    return (
      <div className="flex flex-1 flex-col gap-4 p-4">
        {header}
        <div className="flex flex-1 flex-col items-center justify-center gap-2">
          <p className="text-sm text-hive-text">
            {campaigns.length > 0 ? 'No active event.' : 'No events yet.'}
          </p>
          <p className="text-xs text-hive-muted">
            {campaigns.length > 0
              ? 'Pick a past event above, or create a new one.'
              : 'Create one to start tracking goals, gifts, and bid wars.'}
          </p>
        </div>
      </div>
    )
  }

  const metric = campaign.metric
  const dateRange = `${formatDate(campaign.start_date)} – ${formatDate(campaign.end_date)}`

  return (
    <div className="flex flex-1 flex-col gap-6 overflow-y-auto p-4">
      {header}

      <div>
        <div className="flex items-baseline gap-3">
          <h2 className="text-lg font-semibold text-hive-text">{campaign.name}</h2>
          <span className="text-xs text-hive-muted">{dateRange}</span>
          {isPast && (
            <span className="rounded bg-hive-border px-1.5 py-0.5 text-xs text-hive-muted">
              past event
            </span>
          )}
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

      <MilestoneBoard milestones={campaign.milestones} metric={metric} isPast={isPast} />

      {error && <p className="text-sm text-red-400">{error}</p>}

      <BidWarSection
        channelSlug={channelSlug}
        onError={setError}
        campaignId={campaign.id}
        readOnly={isPast}
      />

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

function MilestoneBoard({
  milestones,
  metric,
  isPast,
}: {
  milestones: Milestone[]
  metric: Metric
  isPast: boolean
}) {
  if (milestones.length === 0) return null

  const nextId = isPast
    ? null
    : (milestones.find((m) => !m.is_unlocked && !m.is_stretch)?.id ??
      milestones.find((m) => !m.is_unlocked)?.id ??
      null)

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
