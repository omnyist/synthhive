import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import barCap from '@/assets/ducke.png'
import type { Campaign } from '@/components/EventEditor'
import { overlayApi, useAutoReload, useOverlayStream, useTransparentBody } from '@/lib/overlay'

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
  useAutoReload()
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
  const next =
    milestones.find((m) => !m.is_unlocked && !m.is_stretch) ??
    milestones.find((m) => !m.is_unlocked) ??
    null

  return (
    <div className="inline-block min-w-96 bg-black/80 px-6 py-5 font-sans">
      {next && <GoalProgress goal={next} metric={metric} />}
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
      <div className="relative mt-3">
        <div className="h-3 overflow-hidden rounded-full bg-white/15">
          <div
            className="h-full rounded-full bg-gradient-to-r from-pink-400 to-fuchsia-400 transition-[width] duration-700"
            style={{ width: `${pct}%` }}
          />
        </div>
        <img
          src={barCap}
          alt=""
          className="absolute top-1/2 h-10 w-10 -translate-x-1/2 -translate-y-1/2 transition-[left] duration-700"
          style={{ left: `${pct}%` }}
        />
      </div>
      <div className="mt-1.5 flex justify-between font-mono text-xl text-white/70">
        <span>
          <span className="font-bold text-white">
            {current.toLocaleString()}
          </span>{' '}
          / {goal.threshold.toLocaleString()}
          {isPoints ? ' pts' : ' subs'}
        </span>
      </div>
      <p className="mt-1.5 text-2xl leading-tight font-extrabold text-white">
        {goal.title}
      </p>
    </>
  );
}
