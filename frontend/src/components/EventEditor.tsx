import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

export interface Milestone {
  id: string
  threshold: number
  title: string
  description: string
  is_unlocked: boolean
  unlocked_at: string | null
  is_stretch: boolean
  goal_unit: string
}

export interface Metric {
  total_subs: number
  total_resubs: number
  total_sub_points: number
  total_bits: number
}

export interface Campaign {
  id: string
  name: string
  slug: string
  description: string
  start_date: string
  end_date: string
  is_active: boolean
  metric: Metric
  milestones: Milestone[]
}

export interface CampaignSummary {
  id: string
  name: string
  slug: string
  description: string
  start_date: string
  end_date: string
  is_active: boolean
  total_subs: number
  total_sub_points: number
}

const inputClass =
  'rounded border border-hive-border bg-hive-dark px-2 py-1.5 text-sm text-hive-text placeholder-hive-muted focus:border-hive-accent focus:outline-none'

export function EventEditor({
  channelSlug,
  campaign,
  onClose,
  onSaved,
}: {
  channelSlug: string
  campaign: Campaign | null // null = create a new event
  onClose: () => void
  onSaved: (campaignId: string) => void
}) {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)

  const [name, setName] = useState(campaign?.name ?? '')
  const [description, setDescription] = useState(campaign?.description ?? '')
  const [startDate, setStartDate] = useState(campaign?.start_date.slice(0, 10) ?? '')
  const [endDate, setEndDate] = useState(campaign?.end_date.slice(0, 10) ?? '')
  const [isActive, setIsActive] = useState(campaign?.is_active ?? false)

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['campaigns', channelSlug] })
    queryClient.invalidateQueries({ queryKey: ['campaign', channelSlug] })
  }

  const saveMutation = useMutation({
    mutationFn: () => {
      // Campaign dates are calendar dates end to end — Synthfunc stores
      // DateFields, so no timezone math on either side of the wire.
      const body = {
        name: name.trim(),
        description: description.trim(),
        start_date: startDate,
        end_date: endDate,
        is_active: isActive,
      }
      return campaign
        ? api<Campaign>(`/api/v1/campaigns/channels/${channelSlug}/${campaign.id}/`, {
            method: 'PATCH',
            body: JSON.stringify(body),
          })
        : api<Campaign>(`/api/v1/campaigns/channels/${channelSlug}/`, {
            method: 'POST',
            body: JSON.stringify(body),
          })
    },
    onSuccess: (saved) => {
      setError(null)
      invalidate()
      onSaved(saved.id)
    },
    onError: (e: Error) => setError(e.message),
  })

  const ready = name.trim() && startDate && endDate

  return (
    <div className="flex flex-col gap-4 rounded-lg border border-hive-border bg-hive-surface p-4">
      <div className="flex items-center">
        <h3 className="text-sm font-semibold text-hive-text">
          {campaign ? `Edit ${campaign.name}` : 'New event'}
        </h3>
        <button
          type="button"
          onClick={onClose}
          className="ml-auto rounded px-2 py-1 text-xs text-hive-muted transition-colors hover:text-hive-text">
          Cancel
        </button>
      </div>

      <div className="flex flex-col gap-2">
        <input
          type="text"
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Event name (e.g. Awesome August)"
          className={inputClass}
        />
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="Description (optional) — shown on the public event page"
          rows={8}
          className={cn(inputClass, 'resize-y font-mono text-xs leading-relaxed')}
        />
        <p className="text-xs text-hive-muted">
          Markdown supported: paragraphs, **bold**, # headings, - lists, [links](url), tables.
        </p>
        <div className="flex items-center gap-2">
          <input
            type="date"
            value={startDate}
            onChange={(e) => setStartDate(e.target.value)}
            className={inputClass}
          />
          <span className="text-xs text-hive-muted">to</span>
          <input
            type="date"
            value={endDate}
            onChange={(e) => setEndDate(e.target.value)}
            className={inputClass}
          />
          <label className="ml-auto flex items-center gap-1.5 text-xs text-hive-text select-none">
            <input
              type="checkbox"
              checked={isActive}
              onChange={(e) => setIsActive(e.target.checked)}
            />
            Active event
          </label>
        </div>
        {isActive && !campaign?.is_active && (
          <p className="text-xs text-hive-muted">
            Activating this event deactivates any other active one.
          </p>
        )}
      </div>

      {campaign && (
        <MilestoneEditor channelSlug={channelSlug} campaign={campaign} onError={setError} />
      )}
      {!campaign && (
        <p className="text-xs text-hive-muted">Save the event first, then add goals to it.</p>
      )}

      {error && <p className="text-sm text-red-400">{error}</p>}

      <button
        type="button"
        disabled={!ready || saveMutation.isPending}
        onClick={() => saveMutation.mutate()}
        className="self-start rounded bg-hive-accent-dim px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-hive-accent-dim/80 disabled:opacity-50">
        {saveMutation.isPending ? 'Saving…' : campaign ? 'Save changes' : 'Create event'}
      </button>
    </div>
  )
}

export function useGoalMutations(channelSlug: string, onError: (message: string | null) => void) {
  const queryClient = useQueryClient()

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['campaigns', channelSlug] })
    queryClient.invalidateQueries({ queryKey: ['campaign', channelSlug] })
  }

  const update = useMutation({
    mutationFn: ({ id, ...body }: { id: string } & Partial<Milestone>) =>
      api<Campaign>(`/api/v1/campaigns/channels/${channelSlug}/milestones/${id}/`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      onError(null)
      invalidate()
    },
    onError: (e: Error) => onError(e.message),
  })

  const remove = useMutation({
    mutationFn: (id: string) =>
      api<Campaign>(`/api/v1/campaigns/channels/${channelSlug}/milestones/${id}/`, {
        method: 'DELETE',
      }),
    onSuccess: () => {
      onError(null)
      invalidate()
    },
    onError: (e: Error) => onError(e.message),
  })

  return { update, remove }
}

function MilestoneEditor({
  channelSlug,
  campaign,
  onError,
}: {
  channelSlug: string
  campaign: Campaign
  onError: (message: string | null) => void
}) {
  const { update: updateMutation, remove: deleteMutation } = useGoalMutations(channelSlug, onError)

  return (
    <div className="flex flex-col gap-1.5">
      <h4 className="text-xs font-medium tracking-wide text-hive-muted uppercase">Goals</h4>
      {campaign.milestones.length === 0 && <p className="text-xs text-hive-muted">No goals yet.</p>}
      {campaign.milestones.map((m) => (
        <MilestoneRow
          key={m.id}
          milestone={m}
          disabled={updateMutation.isPending || deleteMutation.isPending}
          onSave={(changes) => updateMutation.mutate({ id: m.id, ...changes })}
          onDelete={() => {
            if (window.confirm(`Delete goal "${m.title}"?`)) deleteMutation.mutate(m.id)
          }}
        />
      ))}
      <AddMilestoneRow channelSlug={channelSlug} campaign={campaign} onError={onError} />
    </div>
  )
}

function MilestoneRow({
  milestone,
  disabled,
  onSave,
  onDelete,
}: {
  milestone: Milestone
  disabled: boolean
  onSave: (changes: Partial<Milestone>) => void
  onDelete: () => void
}) {
  const [threshold, setThreshold] = useState(String(milestone.threshold))
  const [title, setTitle] = useState(milestone.title)
  const [goalUnit, setGoalUnit] = useState(milestone.goal_unit)
  const [isStretch, setIsStretch] = useState(milestone.is_stretch)

  const parsed = parseInt(threshold, 10)
  const dirty =
    parsed !== milestone.threshold ||
    title !== milestone.title ||
    goalUnit !== milestone.goal_unit ||
    isStretch !== milestone.is_stretch

  return (
    <div className="flex items-center gap-1.5">
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
      {milestone.is_unlocked && <span className="text-xs text-green-300">✓</span>}
      <button
        type="button"
        disabled={disabled || !dirty || !parsed || !title.trim()}
        onClick={() =>
          onSave({
            threshold: parsed,
            title: title.trim(),
            goal_unit: goalUnit,
            is_stretch: isStretch,
          })
        }
        className={cn(
          'shrink-0 rounded px-2 py-1 text-xs font-medium transition-colors disabled:opacity-40',
          dirty ? 'bg-hive-accent-dim text-white hover:bg-hive-accent-dim/80' : 'text-hive-muted',
        )}>
        Save
      </button>
      <button
        type="button"
        disabled={disabled}
        onClick={onDelete}
        className="shrink-0 rounded px-2 py-1 text-xs text-red-400 transition-colors hover:bg-red-500/10 disabled:opacity-40">
        Delete
      </button>
    </div>
  )
}

export function AddMilestoneRow({
  channelSlug,
  campaign,
  onError,
}: {
  channelSlug: string
  campaign: Campaign
  onError: (message: string | null) => void
}) {
  const queryClient = useQueryClient()
  const [threshold, setThreshold] = useState('')
  const [title, setTitle] = useState('')
  const [goalUnit, setGoalUnit] = useState('subs')
  const [isStretch, setIsStretch] = useState(false)

  const createMutation = useMutation({
    mutationFn: () =>
      api<Campaign>(`/api/v1/campaigns/channels/${channelSlug}/${campaign.id}/milestones/`, {
        method: 'POST',
        body: JSON.stringify({
          threshold: parseInt(threshold, 10),
          title: title.trim(),
          goal_unit: goalUnit,
          is_stretch: isStretch,
        }),
      }),
    onSuccess: () => {
      onError(null)
      setThreshold('')
      setTitle('')
      setGoalUnit('subs')
      setIsStretch(false)
      queryClient.invalidateQueries({ queryKey: ['campaigns', channelSlug] })
      queryClient.invalidateQueries({ queryKey: ['campaign', channelSlug] })
    },
    onError: (e: Error) => onError(e.message),
  })

  const parsed = parseInt(threshold, 10)

  return (
    <div className="flex items-center gap-1.5">
      <MilestoneFields
        threshold={threshold}
        title={title}
        goalUnit={goalUnit}
        isStretch={isStretch}
        onThreshold={setThreshold}
        onTitle={setTitle}
        onGoalUnit={setGoalUnit}
        onStretch={setIsStretch}
        placeholderTitle="New goal (e.g. Baiten Kaitos)"
      />
      <button
        type="button"
        disabled={createMutation.isPending || !parsed || !title.trim()}
        onClick={() => createMutation.mutate()}
        className="shrink-0 rounded bg-hive-accent-dim px-2 py-1 text-xs font-medium text-white transition-colors hover:bg-hive-accent-dim/80 disabled:opacity-40">
        Add
      </button>
    </div>
  )
}

export function MilestoneFields({
  threshold,
  title,
  goalUnit,
  isStretch,
  onThreshold,
  onTitle,
  onGoalUnit,
  onStretch,
  placeholderTitle = 'Goal title',
}: {
  threshold: string
  title: string
  goalUnit: string
  isStretch: boolean
  onThreshold: (v: string) => void
  onTitle: (v: string) => void
  onGoalUnit: (v: string) => void
  onStretch: (v: boolean) => void
  placeholderTitle?: string
}) {
  const smallInput =
    'rounded border border-hive-border bg-hive-dark px-2 py-1 text-xs text-hive-text placeholder-hive-muted focus:border-hive-accent focus:outline-none'

  return (
    <>
      <input
        type="number"
        value={threshold}
        onChange={(e) => onThreshold(e.target.value)}
        placeholder="500"
        className={cn(smallInput, 'w-20 font-mono')}
      />
      <input
        type="text"
        value={title}
        onChange={(e) => onTitle(e.target.value)}
        placeholder={placeholderTitle}
        className={cn(smallInput, 'min-w-0 flex-1')}
      />
      <select value={goalUnit} onChange={(e) => onGoalUnit(e.target.value)} className={smallInput}>
        <option value="subs">subs</option>
        <option value="sub_points">sub points</option>
      </select>
      <label className="flex shrink-0 items-center gap-1 text-xs text-hive-muted select-none">
        <input type="checkbox" checked={isStretch} onChange={(e) => onStretch(e.target.checked)} />
        stretch
      </label>
    </>
  )
}
