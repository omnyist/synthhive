import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import type { Campaign } from '@/components/EventEditor'
import { overlayApi, useOverlayStream } from '@/lib/overlay'

/**
 * Ultra-compact goal bar, designed for a ~238×26 OBS browser source:
 * the whole widget is the progress bar — fill as background, current
 * incentive title left, count right, black base (per Spoonee's layout;
 * intentionally NOT transparent). Sized to the viewport, so the OBS
 * source dimensions are the design.
 */
export const Route = createFileRoute('/overlay/$channelSlug/goalbar')({
  component: GoalBarWidget,
  validateSearch: (search: Record<string, unknown>): { key: string } => ({
    key: typeof search.key === 'string' ? search.key : '',
  }),
})

function GoalBarWidget() {
  const { channelSlug } = Route.useParams()
  const { key } = Route.useSearch()

  useOverlayStream(channelSlug, key)

  const { data: campaign } = useQuery({
    queryKey: ['overlay', 'campaign', channelSlug],
    queryFn: () =>
      overlayApi<Campaign | null>(`/api/v1/overlay/channels/${channelSlug}/campaign/?key=${key}`),
    retry: false,
    refetchInterval: 60_000, // slow backstop — SSE drives freshness
    enabled: !!key,
  })

  // No campaign or no goals: a plain black strip, invisible on her panel.
  if (!campaign || campaign.milestones.length === 0) {
    return <div className="h-screen w-screen bg-black" />
  }

  const { metric, milestones } = campaign
  const goal =
    milestones.find((m) => !m.is_unlocked && !m.is_stretch) ??
    milestones.find((m) => !m.is_unlocked) ??
    null

  if (!goal) {
    return (
      <Bar
        pct={100}
        title="All goals cleared!"
        count={`${milestones.length}/${milestones.length}`}
      />
    )
  }

  const isPoints = goal.goal_unit === 'sub_points'
  const current = isPoints ? metric.total_sub_points : metric.total_subs + metric.total_resubs
  const pct = Math.min(100, (current / goal.threshold) * 100)

  return (
    <Bar
      pct={pct}
      title={goal.title}
      count={`${current.toLocaleString()}/${goal.threshold.toLocaleString()}`}
    />
  )
}

function Bar({ pct, title, count }: { pct: number; title: string; count: string }) {
  return (
    <div className="relative h-screen w-screen overflow-hidden bg-black font-sans">
      <div
        className="absolute inset-y-0 left-0 bg-gradient-to-r from-pink-600 to-fuchsia-500 transition-[width] duration-700"
        style={{ width: `${pct}%` }}
      />
      <div className="relative flex h-full items-center justify-between gap-2 px-1.5">
        <span className="truncate text-[11px] leading-none font-semibold text-white [text-shadow:0_1px_2px_rgba(0,0,0,0.9)]">
          {title}
        </span>
        <span className="shrink-0 font-mono text-[11px] leading-none font-bold text-white tabular-nums [text-shadow:0_1px_2px_rgba(0,0,0,0.9)]">
          {count}
        </span>
      </div>
    </div>
  )
}
