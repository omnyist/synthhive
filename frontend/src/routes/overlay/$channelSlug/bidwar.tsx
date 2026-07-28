import { useQuery } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import type { BidWar } from '@/components/BidWarSection'
import { overlayApi, useOverlayStream, useTransparentBody } from '@/lib/overlay'
import { cn } from '@/lib/utils'

export const Route = createFileRoute('/overlay/$channelSlug/bidwar')({
  component: BidWarWidget,
  validateSearch: (search: Record<string, unknown>): { key: string } => ({
    key: typeof search.key === 'string' ? search.key : '',
  }),
})

// Side colors, left to right. 1v1 today; more hues when a multi-way
// war ("hair colors") actually happens.
const SIDE_COLORS = ['text-pink-300', 'text-sky-300']
const SIDE_BARS = ['bg-gradient-to-r from-pink-400 to-fuchsia-400', 'bg-sky-400']

function BidWarWidget() {
  const { channelSlug } = Route.useParams()
  const { key } = Route.useSearch()

  useTransparentBody()
  useOverlayStream(channelSlug, key)

  const { data: wars = [] } = useQuery({
    queryKey: ['overlay', 'bidwars', channelSlug],
    queryFn: () =>
      overlayApi<BidWar[]>(`/api/v1/overlay/channels/${channelSlug}/bidwars/?key=${key}`),
    retry: false,
    refetchInterval: 60_000, // slow backstop — SSE drives freshness
    enabled: !!key,
  })

  const war = wars.find((w) => w.status === 'open') ?? null
  if (!war || war.options.length < 2) return null

  const [a, b] = war.options
  const total = a.total + b.total
  // 50/50 until points land; clamp so neither side's bar disappears.
  const pctA = total === 0 ? 50 : Math.min(92, Math.max(8, (a.total / total) * 100))
  const leader = a.total === b.total ? null : a.total > b.total ? 0 : 1

  return (
    <div className="inline-block min-w-96 rounded-2xl border border-white/10 bg-black/80 px-6 py-5 font-sans">
      <p className="text-center text-xs font-bold tracking-[0.2em] text-white/50 uppercase">
        {war.title}
      </p>

      <div className="mt-2 flex items-end justify-between gap-6">
        <SideScore option={a} side={0} leading={leader === 0} align="left" />
        <span className="pb-1 text-sm font-bold text-white/40">vs</span>
        <SideScore option={b} side={1} leading={leader === 1} align="right" />
      </div>

      <div className="mt-3 flex h-3 gap-0.5 overflow-hidden rounded-full bg-white/15">
        <div
          className={cn('h-full transition-[width] duration-700', SIDE_BARS[0])}
          style={{ width: `${pctA}%` }}
        />
        <div className={cn('h-full flex-1 transition-[width] duration-700', SIDE_BARS[1])} />
      </div>
    </div>
  )
}

function SideScore({
  option,
  side,
  leading,
  align,
}: {
  option: BidWar['options'][number]
  side: number
  leading: boolean
  align: 'left' | 'right'
}) {
  return (
    <div className={cn('flex flex-col', align === 'right' && 'items-end text-right')}>
      <span
        className={cn(
          'text-lg leading-tight font-extrabold',
          leading ? SIDE_COLORS[side] : 'text-white',
        )}>
        {option.name}
      </span>
      <span className="font-mono text-3xl font-black text-white tabular-nums">
        {option.total.toLocaleString()}
      </span>
    </div>
  )
}
