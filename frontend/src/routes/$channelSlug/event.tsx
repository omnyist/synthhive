import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { ActivityFeed } from '@/components/ActivityFeed'
import { BidWarSection } from '@/components/BidWarSection'
import type { Campaign, CampaignSummary, Milestone } from '@/components/EventEditor'
import {
  AddMilestoneRow,
  EventEditor,
  MilestoneFields,
  useGoalMutations,
} from '@/components/EventEditor'
import { MarkdownContent } from '@/components/MarkdownContent'
import { OverlayUrls } from '@/components/OverlayUrls'
import { Button } from '@/components/ui/Button'
import { Select } from '@/components/ui/Input'
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

  const { data: campaignList = [], isLoading: listLoading } = useQuery({
    queryKey: ['campaigns', channelSlug],
    queryFn: () => api<CampaignSummary[]>(`/api/v1/campaigns/channels/${channelSlug}/`),
    retry: false,
  })

  const campaigns = [...campaignList].sort((a, b) => b.start_date.localeCompare(a.start_date))
  const activeId = campaigns.find((c) => c.is_active)?.id ?? null
  const viewingId = selectedId ?? activeId ?? campaigns[0]?.id ?? null

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

  // A non-active event is "past" once its window has closed and
  // "upcoming" before it opens; goals stay editable until it ends.
  // Dates are calendar dates ("2026-08-01"), so compare date-to-date.
  const today = new Date().toISOString().slice(0, 10)
  const isEnded = !!campaign && !campaign.is_active && campaign.end_date.slice(0, 10) < today
  const isUpcoming = !!campaign && !campaign.is_active && campaign.start_date.slice(0, 10) > today
  const statusLabel = campaign?.is_active
    ? null
    : isEnded
      ? 'past event'
      : isUpcoming
        ? 'upcoming'
        : 'inactive'

  const header = (
    <div className="flex items-center gap-2">
      {campaigns.length > 0 && (
        <Select
          value={viewingId ?? ''}
          onChange={(e) => e.target.value && selectCampaign(e.target.value)}
          inset
          className="text-xs">
          {!viewingId && <option value="">Pick an event…</option>}
          {campaigns.map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
              {c.is_active ? ' (active)' : ''}
            </option>
          ))}
        </Select>
      )}
      <div className="ml-auto flex gap-1.5">
        {campaign && mode === 'view' && (
          <Button variant="outline" className="px-2.5" onClick={() => setMode('edit')}>
            Edit
          </Button>
        )}
        {mode === 'view' && (
          <Button variant="solid" className="px-2.5" onClick={() => setMode('create')}>
            New event
          </Button>
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
            {campaigns.length > 0 ? 'No event selected.' : 'No events yet.'}
          </p>
          <p className="text-xs text-hive-muted">
            {campaigns.length > 0
              ? 'Pick an event above, or create a new one.'
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
          {statusLabel && (
            <span className="rounded bg-hive-border px-1.5 py-0.5 text-xs text-hive-muted">
              {statusLabel}
            </span>
          )}
        </div>
        {campaign.description && <DashboardDescription text={campaign.description} />}
      </div>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
        <StatTile label="Subs" value={metric.total_subs} />
        <StatTile label="Resubs" value={metric.total_resubs} />
        <StatTile label="Sub points" value={metric.total_sub_points} />
        <StatTile label="Bits" value={metric.total_bits} />
      </div>

      <MilestoneBoard
        channelSlug={channelSlug}
        campaign={campaign}
        editable={!isEnded}
        showNext={campaign.is_active}
        onError={setError}
      />

      {error && <p className="text-sm text-red-400">{error}</p>}

      <BidWarSection
        channelSlug={channelSlug}
        onError={setError}
        campaignId={campaign.id}
        readOnly={!campaign.is_active}
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

      <ActivityFeed channelSlug={channelSlug} />

      <OverlayUrls channelSlug={channelSlug} />
    </div>
  )
}

/** The description can be pastebin-length — clamp it on the dashboard
 * so it doesn't bury the stat tiles; the public page shows it all. */
function DashboardDescription({ text }: { text: string }) {
  const [expanded, setExpanded] = useState(false)
  const isLong = text.length > 280 || text.split('\n').length > 3

  return (
    <div className="mt-1 max-w-2xl">
      <MarkdownContent
        className={cn('text-xs text-hive-muted', !expanded && isLong && 'line-clamp-3')}>
        {text}
      </MarkdownContent>
      {isLong && (
        <Button
          variant="link"
          className="mt-1 text-xs text-hive-accent"
          onClick={() => setExpanded(!expanded)}>
          {expanded ? 'Show less' : 'Show more'}
        </Button>
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
  channelSlug,
  campaign,
  editable,
  showNext,
  onError,
}: {
  channelSlug: string
  campaign: Campaign
  editable: boolean
  showNext: boolean
  onError: (message: string | null) => void
}) {
  const [adding, setAdding] = useState(false)
  const { milestones, metric } = campaign

  if (milestones.length === 0 && !editable) return null

  const nextId = showNext
    ? (milestones.find((m) => !m.is_unlocked && !m.is_stretch)?.id ??
      milestones.find((m) => !m.is_unlocked)?.id ??
      null)
    : null

  return (
    <div className="flex flex-col gap-1">
      <h3 className="text-xs font-medium tracking-wide text-hive-muted uppercase">Goals</h3>
      {milestones.map((m) => {
        const isPoints = m.goal_unit === 'sub_points'
        // Count goals measure NEW + GIFT subs (total_subs) — resubs
        // aren't new subscriptions. Resubs still earn sub points.
        const current = isPoints ? metric.total_sub_points : metric.total_subs
        return (
          <GoalRow
            key={m.id}
            channelSlug={channelSlug}
            milestone={m}
            current={current}
            isNext={m.id === nextId}
            editable={editable}
            onError={onError}
          />
        )
      })}
      {editable &&
        (adding ? (
          <div className="flex flex-col gap-1.5 rounded border border-hive-border bg-hive-surface px-3 py-2">
            <AddMilestoneRow channelSlug={channelSlug} campaign={campaign} onError={onError} />
            <Button variant="link" className="self-start text-xs" onClick={() => setAdding(false)}>
              Done adding
            </Button>
          </div>
        ) : (
          <Button className="self-start px-1 py-0.5" onClick={() => setAdding(true)}>
            + Add goal
          </Button>
        ))}
    </div>
  )
}

function GoalRow({
  channelSlug,
  milestone: m,
  current,
  isNext,
  editable,
  onError,
}: {
  channelSlug: string
  milestone: Milestone
  current: number
  isNext: boolean
  editable: boolean
  onError: (message: string | null) => void
}) {
  const [editing, setEditing] = useState(false)
  const { update, remove } = useGoalMutations(channelSlug, onError)

  const isPoints = m.goal_unit === 'sub_points'
  const pct = m.is_unlocked ? 100 : Math.min(100, Math.floor((current / m.threshold) * 100))

  if (editing) {
    return (
      <GoalRowEditor
        milestone={m}
        pending={update.isPending || remove.isPending}
        onSave={(changes) =>
          update.mutate({ id: m.id, ...changes }, { onSuccess: () => setEditing(false) })
        }
        onDelete={() => {
          if (window.confirm(`Delete goal "${m.title}"?`)) {
            remove.mutate(m.id, { onSuccess: () => setEditing(false) })
          }
        }}
        onCancel={() => setEditing(false)}
      />
    )
  }

  return (
    <div
      className={cn(
        'group flex flex-col gap-1.5 rounded border px-3 py-2',
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
        {editable && (
          <Button
            className="px-1.5 py-0.5 opacity-0 transition-opacity group-hover:opacity-100"
            onClick={() => setEditing(true)}>
            edit
          </Button>
        )}
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
}

function GoalRowEditor({
  milestone: m,
  pending,
  onSave,
  onDelete,
  onCancel,
}: {
  milestone: Milestone
  pending: boolean
  onSave: (changes: Partial<Milestone>) => void
  onDelete: () => void
  onCancel: () => void
}) {
  const [threshold, setThreshold] = useState(String(m.threshold))
  const [title, setTitle] = useState(m.title)
  const [goalUnit, setGoalUnit] = useState(m.goal_unit)
  const [isStretch, setIsStretch] = useState(m.is_stretch)

  const parsed = parseInt(threshold, 10)

  return (
    <div className="flex items-center gap-1.5 rounded border border-hive-accent bg-hive-surface px-3 py-2">
      <MilestoneFields
        threshold={threshold}
        title={title}
        goalUnit={goalUnit}
        isStretch={isStretch}
        onThreshold={setThreshold}
        onTitle={setTitle}
        onGoalUnit={setGoalUnit}
        onStretch={setIsStretch}
      />
      <Button
        disabled={pending || !parsed || !title.trim()}
        onClick={() =>
          onSave({
            threshold: parsed,
            title: title.trim(),
            goal_unit: goalUnit,
            is_stretch: isStretch,
          })
        }
        variant="solid"
        className="shrink-0 px-2 disabled:opacity-40">
        Save
      </Button>
      <Button disabled={pending} onClick={onCancel} className="shrink-0 px-2 disabled:opacity-40">
        Cancel
      </Button>
      <Button
        disabled={pending}
        onClick={onDelete}
        variant="danger"
        className="shrink-0 px-2 disabled:opacity-40">
        Delete
      </Button>
    </div>
  )
}

// Render a calendar date as-is — never through the viewer's timezone,
// which would shift "2026-08-01" to July 31 west of UTC.
function formatDate(isoDate: string): string {
  const [y, m, d] = isoDate.slice(0, 10).split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d)).toLocaleDateString(undefined, {
    timeZone: 'UTC',
    month: 'short',
    day: 'numeric',
  })
}
