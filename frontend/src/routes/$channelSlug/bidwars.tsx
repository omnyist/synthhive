import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

interface BidWarOption {
  id: string
  name: string
  position: number
  total: number
}

interface BidWar {
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
  created_at: string
}

const QUICK_PACKS = [1, 5, 10, 25, 50, 100]

export const Route = createFileRoute('/$channelSlug/bidwars')({
  component: BidWarsPage,
})

function BidWarsPage() {
  const { channelSlug } = Route.useParams()
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['bidwars', channelSlug] })
    queryClient.invalidateQueries({ queryKey: ['bidwar-allocations', channelSlug] })
  }

  const { data: wars = [], isLoading } = useQuery({
    queryKey: ['bidwars', channelSlug],
    queryFn: () => api<BidWar[]>(`/api/v1/bidwars/channels/${channelSlug}/`),
    retry: false,
  })

  const activeWar = wars.find((w) => w.status === 'open') ?? null

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8">
        <p className="text-hive-muted">Loading bid wars...</p>
      </div>
    )
  }

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-y-auto p-4">
      <div>
        <h2 className="text-sm font-medium text-hive-text">Bid Wars</h2>
        <p className="mt-0.5 text-xs text-hive-muted">
          Gift subs become points. Allocate each gift batch to a side — allocations are a journal,
          so mistakes are corrected with an undo entry, never lost.
        </p>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      {activeWar ? (
        <ActiveWar
          channelSlug={channelSlug}
          war={activeWar}
          onChanged={invalidate}
          onError={setError}
        />
      ) : (
        <CreateWarForm channelSlug={channelSlug} onCreated={invalidate} onError={setError} />
      )}

      {wars.filter((w) => w.status === 'closed').length > 0 && (
        <div className="flex flex-col gap-1">
          <h3 className="text-xs font-medium tracking-wide text-hive-muted uppercase">Past wars</h3>
          {wars
            .filter((w) => w.status === 'closed')
            .map((w) => (
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

  const { data: allocations = [] } = useQuery({
    queryKey: ['bidwar-allocations', channelSlug, war.id],
    queryFn: () =>
      api<Allocation[]>(`/api/v1/bidwars/channels/${channelSlug}/${war.id}/allocations/`),
    retry: false,
  })

  const allocateMutation = useMutation({
    mutationFn: (input: { option_id: string; points: number; note: string }) =>
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

  const undoLast = () => {
    const last = allocations[0]
    if (!last) return
    allocateMutation.mutate({
      option_id: last.option_id,
      points: -last.points,
      note: `undo: ${last.note || `${last.points} to ${last.option_name}`}`,
    })
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex items-center gap-3">
        <h3 className="text-lg font-semibold text-hive-text">{war.title}</h3>
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
          <OptionCard
            key={option.id}
            option={option}
            isLeading={option.total === leader && leader > 0}
            disabled={allocateMutation.isPending}
            onAllocate={(points, note) =>
              allocateMutation.mutate({ option_id: option.id, points, note })
            }
          />
        ))}
      </div>

      <div className="flex flex-col gap-1">
        <div className="flex items-center">
          <h3 className="text-xs font-medium tracking-wide text-hive-muted uppercase">
            Allocation history
          </h3>
          {allocations.length > 0 && (
            <button
              type="button"
              onClick={undoLast}
              disabled={allocateMutation.isPending}
              className="ml-auto rounded px-2 py-1 text-xs text-red-400 transition-colors hover:bg-red-400/10 disabled:opacity-50">
              Undo last
            </button>
          )}
        </div>
        {allocations.length === 0 && (
          <p className="py-3 text-center text-sm text-hive-muted">No allocations yet.</p>
        )}
        {allocations.map((a) => (
          <div
            key={a.id}
            className="flex items-center gap-3 rounded px-3 py-1.5 text-sm hover:bg-hive-surface">
            <span
              className={cn(
                'w-14 text-right font-mono',
                a.points < 0 ? 'text-red-400' : 'text-hive-text',
              )}>
              {a.points > 0 ? `+${a.points}` : a.points}
            </span>
            <span className="text-hive-text">{a.option_name}</span>
            {a.note && <span className="truncate text-xs text-hive-muted">{a.note}</span>}
            <span className="ml-auto shrink-0 text-xs text-hive-muted">
              {new Date(a.created_at).toLocaleTimeString(undefined, {
                hour: '2-digit',
                minute: '2-digit',
              })}
            </span>
          </div>
        ))}
      </div>
    </div>
  )
}

function OptionCard({
  option,
  isLeading,
  disabled,
  onAllocate,
}: {
  option: BidWarOption
  isLeading: boolean
  disabled: boolean
  onAllocate: (points: number, note: string) => void
}) {
  const [custom, setCustom] = useState('')
  const [note, setNote] = useState('')

  const submit = (points: number) => {
    if (!points || Number.isNaN(points)) return
    onAllocate(points, note.trim())
    setCustom('')
    setNote('')
  }

  return (
    <div
      className={cn(
        'flex flex-col gap-3 rounded-lg border p-4',
        isLeading
          ? 'border-hive-accent bg-hive-accent-dim/10'
          : 'border-hive-border bg-hive-surface',
      )}>
      <div className="flex items-baseline gap-2">
        <span className="text-sm font-medium text-hive-text">{option.name}</span>
        {isLeading && <span className="text-xs text-hive-accent">leading</span>}
      </div>
      <span className="font-mono text-4xl font-bold text-hive-text">{option.total}</span>

      <div className="flex flex-wrap gap-1.5">
        {QUICK_PACKS.map((n) => (
          <button
            key={n}
            type="button"
            disabled={disabled}
            onClick={() => submit(n)}
            className="rounded bg-hive-border px-2.5 py-1 font-mono text-xs text-hive-text transition-colors hover:bg-hive-accent-dim hover:text-white disabled:opacity-50">
            +{n}
          </button>
        ))}
      </div>

      <div className="flex gap-1.5">
        <input
          type="number"
          value={custom}
          onChange={(e) => setCustom(e.target.value)}
          placeholder="custom"
          className="w-20 rounded border border-hive-border bg-hive-dark px-2 py-1 font-mono text-xs text-hive-text placeholder-hive-muted focus:border-hive-accent focus:outline-none"
        />
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="note (e.g. gifter name)"
          className="min-w-0 flex-1 rounded border border-hive-border bg-hive-dark px-2 py-1 text-xs text-hive-text placeholder-hive-muted focus:border-hive-accent focus:outline-none"
        />
        <button
          type="button"
          disabled={disabled || !custom}
          onClick={() => submit(parseInt(custom, 10))}
          className="shrink-0 rounded bg-hive-accent-dim px-2.5 py-1 text-xs font-medium text-white transition-colors hover:bg-hive-accent-dim/80 disabled:opacity-50">
          Add
        </button>
      </div>
    </div>
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
