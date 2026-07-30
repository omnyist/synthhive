import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useEffect } from 'react'
import type { BidWar } from '@/components/BidWarSection'
import type { Campaign, Milestone } from '@/components/EventEditor'
import { MarkdownContent } from '@/components/MarkdownContent'
import { overlayApi } from '@/lib/overlay'
import { cn } from '@/lib/utils'

type PublicCampaign = Campaign & { bid_wars: BidWar[] }

export const Route = createFileRoute('/$channelSlug/$campaignSlug')({
  component: PublicEventPage,
})

function PublicEventPage() {
  const { channelSlug, campaignSlug } = Route.useParams()

  const { data: campaign, isError } = useQuery({
    queryKey: ['public-campaign', channelSlug, campaignSlug],
    queryFn: () =>
      overlayApi<PublicCampaign>(
        `/api/v1/public/channels/${channelSlug}/campaigns/${campaignSlug}/`,
      ),
    retry: false,
    refetchInterval: 60_000,
  })

  useEffect(() => {
    if (campaign) document.title = campaign.name
  }, [campaign])

  if (isError) {
    return (
      <div className="flex min-h-screen items-center justify-center">
        <p className="text-sm text-hive-muted">There's no event here.</p>
      </div>
    )
  }

  if (!campaign) return null

  const { metric } = campaign
  const hasProgress = metric.total_subs + metric.total_resubs + metric.total_bits > 0
  const nextId = campaign.is_active
    ? (campaign.milestones.find((m) => !m.is_unlocked && !m.is_stretch)?.id ?? null)
    : null

  return (
    <div className="mx-auto max-w-2xl px-6 py-14">
      <header>
        <h1 className="text-3xl font-bold tracking-tight text-hive-text">{campaign.name}</h1>
        <p className="mt-1 text-sm text-hive-muted">
          {formatDate(campaign.start_date)} – {formatDate(campaign.end_date)} · {channelSlug}
        </p>
        {campaign.description && (
          <MarkdownContent className="mt-4 text-hive-text/90">
            {campaign.description}
          </MarkdownContent>
        )}
        {hasProgress && (
          <p className="mt-4 font-mono text-sm text-hive-muted">
            {metric.total_subs.toLocaleString()} subs · {metric.total_resubs.toLocaleString()}{' '}
            resubs · {metric.total_bits.toLocaleString()} bits so far
          </p>
        )}
      </header>

      {campaign.milestones.length > 0 && (
        <section className="mt-10">
          <h2 className="text-xs font-semibold tracking-[0.15em] text-hive-muted uppercase">
            Goals
          </h2>
          <ul className="mt-3">
            {campaign.milestones.map((m) => (
              <GoalLine key={m.id} goal={m} isNext={m.id === nextId} />
            ))}
          </ul>
        </section>
      )}

      {campaign.bid_wars.length > 0 && (
        <section className="mt-10">
          <h2 className="text-xs font-semibold tracking-[0.15em] text-hive-muted uppercase">
            Bid war
          </h2>
          {campaign.bid_wars.map((w) => (
            <WarLine key={w.id} war={w} />
          ))}
        </section>
      )}
    </div>
  )
}

function GoalLine({ goal, isNext }: { goal: Milestone; isNext: boolean }) {
  const isPoints = goal.goal_unit === 'sub_points'

  return (
    <li
      className={cn(
        'flex items-baseline gap-3 border-l-2 py-1.5 pl-3',
        isNext ? 'border-hive-accent' : 'border-transparent',
      )}>
      <span className="w-20 shrink-0 text-right font-mono text-sm whitespace-nowrap text-hive-muted">
        {goal.threshold.toLocaleString()}
        {isPoints && <span className="text-xs"> pts</span>}
      </span>
      <span
        className={cn(
          'text-[15px]',
          goal.is_unlocked
            ? 'text-hive-muted line-through decoration-hive-muted/50'
            : 'text-hive-text',
        )}>
        {goal.title}
      </span>
      {goal.is_unlocked && <span className="text-sm text-green-400">✓</span>}
      {goal.is_stretch && (
        <span className="rounded bg-yellow-500/15 px-1.5 py-0.5 text-[11px] text-yellow-300/90">
          stretch
        </span>
      )}
    </li>
  )
}

function WarLine({ war }: { war: BidWar }) {
  const leader = Math.max(...war.options.map((o) => o.total))

  return (
    <div className="mt-3">
      <p className="text-[15px] text-hive-text">{war.title}</p>
      <p className="mt-1 font-mono text-sm text-hive-muted">
        {war.options.map((o, i) => (
          <span key={o.id}>
            {i > 0 && <span className="text-hive-muted/50"> · </span>}
            <span className={cn(o.total === leader && leader > 0 && 'font-bold text-hive-text')}>
              {o.name} {o.total.toLocaleString()}
            </span>
          </span>
        ))}
        {war.status === 'closed' && <span className="text-hive-muted/60"> — final</span>}
      </p>
    </div>
  )
}

function formatDate(iso: string): string {
  return new Date(iso).toLocaleDateString(undefined, {
    month: 'long',
    day: 'numeric',
    year: 'numeric',
  })
}
