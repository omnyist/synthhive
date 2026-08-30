import type { ButtonHTMLAttributes, HTMLAttributes, ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * The selectable list that commands, counters and aliases all use.
 *
 * All three had the same scroll container, the same row (down to
 * `bg-hive-accent-dim/20` when selected), and the same centred empty
 * state — copied three times, drifting only in gap-2 vs gap-3. This is
 * a genuine second primitive rather than a Button variant: a row is a
 * full-width record you pick, not a control you press.
 */

export function List({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('flex min-h-0 flex-1 flex-col gap-px overflow-y-auto', className)}
      {...props}
    />
  )
}

interface ListRowProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  selected?: boolean
  /** Disabled records stay readable but visibly inactive. */
  dimmed?: boolean
}

export function ListRow({
  selected = false,
  dimmed = false,
  className,
  type = 'button',
  ...props
}: ListRowProps) {
  return (
    <button
      type={type}
      className={cn(
        'flex items-center gap-3 rounded px-3 py-2 text-left text-sm transition-colors',
        selected
          ? 'bg-hive-accent-dim/20 text-hive-text'
          : 'text-hive-muted hover:bg-hive-surface hover:text-hive-text',
        dimmed && 'opacity-50',
        className,
      )}
      {...props}
    />
  )
}

export function ListEmpty({ children }: { children: ReactNode }) {
  return <p className="px-3 py-4 text-center text-sm text-hive-muted">{children}</p>
}
