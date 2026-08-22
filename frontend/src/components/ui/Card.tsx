import type { HTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

/** Panel surface — border, surface fill, padding. */
export function Card({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('rounded-lg border border-hive-border bg-hive-surface p-4', className)}
      {...props}
    />
  )
}
