import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

export interface BidWarOption {
  id: string
  name: string
  position: number
  total: number
}

export interface BidWar {
  id: string
  title: string
  status: string
  created_at: string
  closed_at: string | null
  options: BidWarOption[]
}

interface Allocation {
  id: string
  option_id: string
  option_name: string
  points: number
  note: string
  source_event_id: string | null
  created_at: string
}

interface PendingGift {
  event_id: string
  gifter: string
  count: number
  tier: number | null
  timestamp: string
}

export function BidWarSection({
  channelSlug,
  onError,
  campaignId,
  readOnly = false,
}: {
  channelSlug: string
  onError: (message: string | null) => void
  campaignId?: string
  readOnly?: boolean
}) {
  const queryClient = useQueryClient()

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['bidwars', channelSlug] })
    queryClient.invalidateQueries({ queryKey: ['bidwar-allocations', channelSlug] })
    queryClient.invalidateQueries({ queryKey: ['pending-gifts', channelSlug] })
  }

  const params = readOnly && campaignId ? `?campaign_id=${campaignId}` : ''
  const { data: wars = [] } = useQuery({
    queryKey: ['bidwars', channelSlug, campaignId ?? 'active'],
    queryFn: () => api<BidWar[]>(`/api/v1/bidwars/channels/${channelSlug}/${params}`),
    retry: false,
  })

  const activeWar = wars.find((w) => w.status === 'open') ?? null
  const pastWars = readOnly ? wars : wars.filter((w) => w.status === 'closed')

  if (readOnly && wars.length === 0) return null

  return (
    <div className="flex flex-col gap-3">
      <h3 className="text-xs font-medium tracking-wide text-hive-muted uppercase">
        {readOnly ? 'Bid wars' : 'Bid war'}
      </h3>

      {!readOnly &&
        (activeWar ? (
          <ActiveWar
            channelSlug={channelSlug}
            war={activeWar}
            onChanged={invalidate}
            onError={onError}
          />
        ) : (
          <CreateWarForm channelSlug={channelSlug} onCreated={invalidate} onError={onError} />
        ))}

      {pastWars.length > 0 && (
        <div className="flex flex-col gap-1">
          {pastWars.map((w) => (
            <div
              key={w.id}
              className="flex items-center gap-3 rounded border border-hive-border bg-hive-surface px-3 py-2 text-sm">
              <span className="text-hive-text">{w.title}</span>
              <span className="ml-auto text-xs text-hive-muted">
                {w.options.map((o) => `${o.name} ${o.total}`).join(' · ')}
              </span>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function ActiveWar({
  channelSlug,
  war,
  onChanged,
  onError,
}: {
  channelSlug: string
  war: BidWar
  onChanged: () => void
  onError: (message: string | null) => void
}) {
  const leader = Math.max(...war.options.map((o) => o.total))

  const { data: pendingGifts = [], isError: pendingFailed } = useQuery({
    queryKey: ['pending-gifts', channelSlug],
    queryFn: () => api<PendingGift[]>(`/api/v1/bidwars/channels/${channelSlug}/pending-gifts/`),
    retry: false,
    refetchInterval: 120_000, // slow backstop — SSE drives freshness
  })

  const { data: allocations = [] } = useQuery({
    queryKey: ['bidwar-allocations', channelSlug, war.id],
    queryFn: () =>
      api<Allocation[]>(`/api/v1/bidwars/channels/${channelSlug}/${war.id}/allocations/`),
    retry: false,
  })

  const allocateMutation = useMutation({
    mutationFn: (input: {
      option_id: string
      points?: number
      note?: string
      source_event_id?: string
    }) =>
      api<BidWar>(`/api/v1/bidwars/channels/${channelSlug}/${war.id}/allocations/`, {
        method: 'POST',
        body: JSON.stringify(input),
      }),
    onSuccess: () => {
      onError(null)
      onChanged()
    },
    onError: (e: Error) => onError(e.message),
  })

  const closeMutation = useMutation({
    mutationFn: () =>
      api<BidWar>(`/api/v1/bidwars/channels/${channelSlug}/${war.id}/`, {
        method: 'PATCH',
        body: JSON.stringify({ status: 'closed' }),
      }),
    onSuccess: onChanged,
    onError: (e: Error) => onError(e.message),
  })

  const undo = (a: Allocation) => {
    allocateMutation.mutate({
      option_id: a.option_id,
      points: -a.points,
      note: `undo: ${a.note || `${a.points} to ${a.option_name}`}`,
      source_event_id: a.source_event_id ?? undefined,
    })
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <h4 className="text-lg font-semibold text-hive-text">{war.title}</h4>
        <button
          type="button"
          onClick={() => window.confirm(`Close "${war.title}"?`) && closeMutation.mutate()}
          className="ml-auto rounded border border-hive-border px-2.5 py-1 text-xs text-hive-muted transition-colors hover:text-hive-text">
          Close war
        </button>
      </div>

      <div
        className={cn(
          'grid gap-3',
          war.options.length === 2 ? 'grid-cols-2' : 'grid-cols-1 sm:grid-cols-3',
        )}>
        {war.options.map((option) => (
          <div
            key={option.id}
            className={cn(
              'flex flex-col gap-1 rounded-lg border p-4',
              option.total === leader && leader > 0
                ? 'border-hive-accent bg-hive-accent-dim/10'
                : 'border-hive-border bg-hive-surface',
            )}>
            <div className="flex items-baseline gap-2">
              <span className="text-sm font-medium text-hive-text">{option.name}</span>
              {option.total === leader && leader > 0 && (
                <span className="text-xs text-hive-accent">leading</span>
              )}
            </div>
            <span className="font-mono text-4xl font-bold text-hive-text">{option.total}</span>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-1">
        <h4 className="text-xs font-medium tracking-wide text-hive-muted uppercase">
          Pending gifts
        </h4>
        {pendingFailed ? (
          // A dead queue must never masquerade as an empty one — that
          // cost a whole stream of manual bookkeeping on day one.
          <p className="py-2 text-sm text-red-400">
            Couldn't load the gift queue — assignments below still work.
          </p>
        ) : (
          pendingGifts.length === 0 && (
            <p className="py-2 text-sm text-hive-muted">
              No unallocated gift batches. New gifts land here automatically.
            </p>
          )
        )}
        {pendingGifts.map((g) => (
          <div
            key={g.event_id}
            className="flex items-center gap-3 rounded border border-hive-border bg-hive-surface px-3 py-2 text-sm">
            <span className="font-mono font-bold text-hive-text">×{g.count}</span>
            <span className="text-hive-text">{g.gifter}</span>
            {g.tier != null && g.tier > 1 && (
              <span className="rounded bg-hive-border px-1.5 py-0.5 text-xs text-hive-muted">
                T{g.tier}
              </span>
            )}
            <span className="text-xs text-hive-muted">
              {new Date(g.timestamp).toLocaleTimeString(undefined, {
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
            <div className="ml-auto flex gap-1.5">
              {war.options.map((option) => (
                <button
                  key={option.id}
                  type="button"
                  disabled={allocateMutation.isPending}
                  onClick={() =>
                    allocateMutation.mutate({
                      option_id: option.id,
                      source_event_id: g.event_id,
                    })
                  }
                  className="rounded bg-hive-accent-dim px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-hive-accent-dim/80 disabled:opacity-50">
                  → {option.name}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>

      <div className="flex flex-col gap-1">
        <h4 className="text-xs font-medium tracking-wide text-hive-muted uppercase">
          Allocation history
        </h4>
        {allocations.length === 0 && (
          <p className="py-2 text-center text-sm text-hive-muted">No allocations yet.</p>
        )}
        {allocations.map((a) => (
          <div
            key={a.id}
            className="group flex items-center gap-3 rounded px-3 py-1.5 text-sm hover:bg-hive-surface">
            <span
              className={cn(
                'w-14 text-right font-mono',
                a.points < 0 ? 'text-red-400' : 'text-hive-text',
              )}>
              {a.points > 0 ? `+${a.points}` : a.points}
            </span>
            <span className="text-hive-text">{a.option_name}</span>
            {a.note && <span className="truncate text-xs text-hive-muted">{a.note}</span>}
            <span className="ml-auto w-12 shrink-0 text-right">
              {a.points > 0 && (
                <button
                  type="button"
                  disabled={allocateMutation.isPending}
                  onClick={() => undo(a)}
                  className="rounded px-2 py-0.5 text-xs text-red-400 opacity-0 transition-opacity group-hover:opacity-100 disabled:opacity-50">
                  undo
                </button>
              )}
            </span>
            <span className="w-16 shrink-0 text-right text-xs text-hive-muted">
              {new Date(a.created_at).toLocaleTimeString(undefined, {
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
          </div>
        ))}
      </div>

      <ManualAdjustment
        options={war.options}
        disabled={allocateMutation.isPending}
        onAllocate={(optionId, points, note) =>
          allocateMutation.mutate({ option_id: optionId, points, note })
        }
      />
    </div>
  )
}

function ManualAdjustment({
  options,
  disabled,
  onAllocate,
}: {
  options: BidWarOption[]
  disabled: boolean
  onAllocate: (optionId: string, points: number, note: string) => void
}) {
  const [optionId, setOptionId] = useState(options[0]?.id ?? '')
  const [points, setPoints] = useState('')
  const [note, setNote] = useState('')

  const parsed = parseInt(points, 10)

  return (
    <details className="rounded border border-hive-border">
      <summary className="cursor-pointer px-3 py-2 text-xs text-hive-muted select-none">
        Manual adjustment (for gifts outside the queue)
      </summary>
      <div className="flex gap-1.5 border-t border-hive-border p-3">
        <select
          value={optionId}
          onChange={(e) => setOptionId(e.target.value)}
          className="rounded border border-hive-border bg-hive-dark px-2 py-1 text-xs text-hive-text focus:border-hive-accent focus:outline-none">
          {options.map((o) => (
            <option key={o.id} value={o.id}>
              {o.name}
            </option>
          ))}
        </select>
        <input
          type="number"
          value={points}
          onChange={(e) => setPoints(e.target.value)}
          placeholder="points (± allowed)"
          className="w-32 rounded border border-hive-border bg-hive-dark px-2 py-1 font-mono text-xs text-hive-text placeholder-hive-muted focus:border-hive-accent focus:outline-none"
        />
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="note"
          className="min-w-0 flex-1 rounded border border-hive-border bg-hive-dark px-2 py-1 text-xs text-hive-text placeholder-hive-muted focus:border-hive-accent focus:outline-none"
        />
        <button
          type="button"
          disabled={disabled || !parsed || !optionId}
          onClick={() => {
            onAllocate(optionId, parsed, note.trim())
            setPoints('')
            setNote('')
          }}
          className="shrink-0 rounded bg-hive-accent-dim px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-hive-accent-dim/80 disabled:opacity-50">
          Add
        </button>
      </div>
    </details>
  )
}

function CreateWarForm({
  channelSlug,
  onCreated,
  onError,
}: {
  channelSlug: string
  onCreated: () => void
  onError: (message: string | null) => void
}) {
  const [title, setTitle] = useState('')
  const [optionA, setOptionA] = useState('')
  const [optionB, setOptionB] = useState('')

  const createMutation = useMutation({
    mutationFn: () =>
      api<BidWar>(`/api/v1/bidwars/channels/${channelSlug}/`, {
        method: 'POST',
        body: JSON.stringify({ title, options: [optionA, optionB] }),
      }),
    onSuccess: () => {
      onError(null)
      setTitle('')
      setOptionA('')
      setOptionB('')
      onCreated()
    },
    onError: (e: Error) => onError(e.message),
  })

  const ready = title.trim() && optionA.trim() && optionB.trim()

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-hive-border bg-hive-surface p-4">
      <p className="text-sm text-hive-text">No open bid war. Start one:</p>
      <input
        type="text"
        value={title}
        onChange={(e) => setTitle(e.target.value)}
        placeholder="Title (e.g. Which game first?)"
        className="rounded border border-hive-border bg-hive-dark px-2 py-1.5 text-sm text-hive-text placeholder-hive-muted focus:border-hive-accent focus:outline-none"
      />
      <div className="flex gap-2">
        <input
          type="text"
          value={optionA}
          onChange={(e) => setOptionA(e.target.value)}
          placeholder="Side A"
          className="flex-1 rounded border border-hive-border bg-hive-dark px-2 py-1.5 text-sm text-hive-text placeholder-hive-muted focus:border-hive-accent focus:outline-none"
        />
        <span className="self-center text-xs text-hive-muted">vs</span>
        <input
          type="text"
          value={optionB}
          onChange={(e) => setOptionB(e.target.value)}
          placeholder="Side B"
          className="flex-1 rounded border border-hive-border bg-hive-dark px-2 py-1.5 text-sm text-hive-text placeholder-hive-muted focus:border-hive-accent focus:outline-none"
        />
      </div>
      <button
        type="button"
        disabled={!ready || createMutation.isPending}
        onClick={() => createMutation.mutate()}
        className="self-start rounded bg-hive-accent-dim px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-hive-accent-dim/80 disabled:opacity-50">
        {createMutation.isPending ? 'Creating…' : 'Start bid war'}
      </button>
    </div>
  )
}
