import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { createFileRoute } from '@tanstack/react-router'
import { useState } from 'react'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

interface Invite {
  id: string
  code: string
  status: string
  created_at: string
  expires_at: string | null
  used_at: string | null
  completed_at: string | null
  channel_name: string | null
}

interface Me {
  is_staff: boolean
}

const STATUS_STYLES: Record<string, string> = {
  pending: 'bg-hive-accent-dim/20 text-hive-accent',
  awaiting_bot: 'bg-yellow-500/20 text-yellow-300',
  completed: 'bg-green-500/20 text-green-300',
  expired: 'bg-red-500/15 text-red-300',
}

export const Route = createFileRoute('/invites')({
  component: InvitesPage,
})

function inviteLink(code: string): string {
  return `${window.location.origin}/invite/${code}/`
}

function formatDate(iso: string | null): string {
  if (!iso) return '—'
  return new Date(iso).toLocaleDateString(undefined, {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function InvitesPage() {
  const queryClient = useQueryClient()
  const [error, setError] = useState<string | null>(null)
  const [copiedId, setCopiedId] = useState<string | null>(null)

  const { data: me } = useQuery<Me>({
    queryKey: ['me'],
    queryFn: () => api<Me>('/api/v1/me'),
    retry: false,
  })

  const { data: invites = [], isLoading } = useQuery({
    queryKey: ['invites'],
    queryFn: () => api<Invite[]>('/api/v1/invites/'),
  })

  const createMutation = useMutation({
    mutationFn: () => api<Invite>('/api/v1/invites/', { method: 'POST', body: '{}' }),
    onSuccess: () => {
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['invites'] })
    },
    onError: (e: Error) => setError(e.message),
  })

  const deleteMutation = useMutation({
    mutationFn: (id: string) => api(`/api/v1/invites/${id}/`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['invites'] }),
    onError: (e: Error) => setError(e.message),
  })

  async function copyLink(inv: Invite) {
    try {
      await navigator.clipboard.writeText(inviteLink(inv.code))
      setCopiedId(inv.id)
      setTimeout(() => setCopiedId((id) => (id === inv.id ? null : id)), 2000)
    } catch {
      setError('Could not copy to clipboard.')
    }
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center p-8">
        <p className="text-hive-muted">Loading invites...</p>
      </div>
    )
  }

  const isStaff = me?.is_staff ?? false

  return (
    <div className="flex flex-1 flex-col gap-4 overflow-hidden p-4">
      <div className="flex items-start justify-between gap-4">
        <div>
          <h2 className="text-sm font-medium text-hive-text">Invites</h2>
          <p className="mt-0.5 text-xs text-hive-muted">
            Onboard a new channel: create an invite, send the link, and they connect their channel
            and bot.
          </p>
        </div>
        {isStaff && (
          <button
            type="button"
            onClick={() => createMutation.mutate()}
            disabled={createMutation.isPending}
            className="shrink-0 rounded bg-hive-accent-dim px-3 py-1.5 text-sm font-medium text-white transition-colors hover:bg-hive-accent-dim/80 disabled:opacity-50">
            {createMutation.isPending ? 'Creating…' : '+ New invite'}
          </button>
        )}
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto">
        {invites.map((inv) => {
          const shareable = inv.status === 'pending' || inv.status === 'awaiting_bot'
          return (
            <div
              key={inv.id}
              className="flex flex-col gap-2 rounded border border-hive-border bg-hive-surface p-3">
              <div className="flex items-center gap-3">
                <span
                  className={cn(
                    'rounded px-2 py-0.5 text-xs font-medium capitalize',
                    STATUS_STYLES[inv.status] ?? 'bg-hive-border text-hive-muted',
                  )}>
                  {inv.status.replace('_', ' ')}
                </span>
                <span className="font-mono text-sm text-hive-text">{inv.code}</span>
                {inv.channel_name && (
                  <span className="text-xs text-hive-muted">#{inv.channel_name}</span>
                )}
                {isStaff && (
                  <button
                    type="button"
                    onClick={() =>
                      window.confirm(`Delete invite ${inv.code}?`) && deleteMutation.mutate(inv.id)
                    }
                    className="ml-auto rounded px-2 py-1 text-xs text-red-400 transition-colors hover:bg-red-400/10">
                    Delete
                  </button>
                )}
              </div>

              {shareable && (
                <div className="flex items-center gap-2">
                  <input
                    readOnly
                    value={inviteLink(inv.code)}
                    onFocus={(e) => e.currentTarget.select()}
                    className="min-w-0 flex-1 rounded border border-hive-border bg-hive-dark px-2 py-1 font-mono text-xs text-hive-muted"
                  />
                  <button
                    type="button"
                    onClick={() => copyLink(inv)}
                    className={cn(
                      'shrink-0 rounded px-2.5 py-1 text-xs font-medium transition-colors',
                      copiedId === inv.id
                        ? 'bg-green-500/20 text-green-300'
                        : 'bg-hive-border text-hive-text hover:bg-hive-border/70',
                    )}>
                    {copiedId === inv.id ? 'Copied' : 'Copy link'}
                  </button>
                </div>
              )}

              <div className="flex gap-4 text-xs text-hive-muted">
                <span>Created {formatDate(inv.created_at)}</span>
                <span>Expires {formatDate(inv.expires_at)}</span>
              </div>
            </div>
          )
        })}

        {invites.length === 0 && (
          <p className="px-3 py-8 text-center text-sm text-hive-muted">
            {isStaff ? 'No invites yet. Create one to onboard a new channel.' : 'No invites.'}
          </p>
        )}
      </div>
    </div>
  )
}
