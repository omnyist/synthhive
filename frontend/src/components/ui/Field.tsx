import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

/**
 * A label above a control. Trivial, and repeated in every form — which
 * is exactly why it drifted: some labels were text-xs text-hive-muted,
 * others weren't.
 *
 * Not wired to htmlFor/id yet. Doing that properly means generating ids
 * (useId) and threading them, which is worth doing when these become
 * real form controls rather than a rename of what's already here.
 */
export function Field({
  label,
  hint,
  className,
  children,
}: {
  label: string
  hint?: string
  className?: string
  children: ReactNode
}) {
  return (
    <div className={cn('flex flex-col gap-1', className)}>
      <span className="text-xs text-hive-muted">{label}</span>
      {children}
      {hint && <span className="text-xs text-hive-muted">{hint}</span>}
    </div>
  )
}
