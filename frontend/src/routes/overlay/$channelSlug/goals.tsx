import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import type { Campaign } from '@/components/EventEditor'
import { overlayApi, useOverlayStream, useTransparentBody } from '@/lib/overlay'

export const Route = createFileRoute('/overlay/$channelSlug/goals')({
  component: GoalsWidget,
  validateSearch: (search: Record<string, unknown>): { key: string } => ({
    key: typeof search.key === 'string' ? search.key : '',
  }),
})

function GoalsWidget() {
  const { channelSlug } = Route.useParams()
  const { key } = Route.useSearch()

  useTransparentBody()
  useOverlayStream(channelSlug, key)

  const { data: campaign } = useQuery({
    queryKey: ['overlay', 'campaign', channelSlug],
    queryFn: () =>
      overlayApi<Campaign | null>(`/api/v1/overlay/channels/${channelSlug}/campaign/?key=${key}`),
    retry: false,
    refetchInterval: 60_000, // slow backstop — SSE drives freshness
    enabled: !!key,
  })

  // A widget with nothing to show renders nothing: transparent, silent.
  if (!campaign || campaign.milestones.length === 0) return null

  const { metric, milestones } = campaign
  const core = milestones.filter((m) => !m.is_stretch)
  const unlocked = core.filter((m) => m.is_unlocked).length
  const next =
    milestones.find((m) => !m.is_unlocked && !m.is_stretch) ??
    milestones.find((m) => !m.is_unlocked) ??
    null
  const after = next
    ? (milestones.find((m) => !m.is_unlocked && m.threshold > next.threshold) ?? null)
    : null

  return (
    <div className="inline-block min-w-96 rounded-2xl border border-white/10 bg-black/80 px-6 py-5 font-sans">
      <div className="flex items-baseline justify-between gap-6">
        <span className="text-xs font-bold tracking-[0.2em] text-pink-300 uppercase">
          {next ? 'Next goal' : 'All goals complete!'}
        </span>
        <span className="font-mono text-xs font-medium text-white/50">
          {unlocked}/{core.length} unlocked
        </span>
      </div>

      {next && <GoalProgress goal={next} metric={metric} />}

      {after && (
        <p className="mt-3 truncate text-sm text-white/40">
          then · {after.title}{' '}
          <span className="font-mono">
            ({after.threshold.toLocaleString()}
            {after.goal_unit === 'sub_points' ? ' pts' : ''})
          </span>
        </p>
      )}
    </div>
  )
}

function GoalProgress({
  goal,
  metric,
}: {
  goal: Campaign['milestones'][number]
  metric: Campaign['metric']
}) {
  const isPoints = goal.goal_unit === 'sub_points'
  // Count goals measure NEW + GIFT subs (total_subs) — resubs aren't
  // new subscriptions. Resubs still earn sub points.
  const current = isPoints ? metric.total_sub_points : metric.total_subs
  const pct = Math.min(100, (current / goal.threshold) * 100)

  return (
    <>
      <p className="mt-1.5 text-2xl leading-tight font-extrabold text-white">{goal.title}</p>
      <div className="mt-3 h-3 overflow-hidden rounded-full bg-white/15">
        <div
          className="h-full rounded-full bg-gradient-to-r from-pink-400 to-fuchsia-400 transition-[width] duration-700"
          style={{ width: `${pct}%` }}
        />
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-sm text-white/70">
        <span>
          <span className="font-bold text-white">{current.toLocaleString()}</span> /{' '}
          {goal.threshold.toLocaleString()}
          {isPoints ? ' pts' : ' subs'}
        </span>
        <span>{Math.floor(pct)}%</span>
      </div>
    </>
  )
}
