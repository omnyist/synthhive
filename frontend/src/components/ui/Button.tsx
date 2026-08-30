import type { ButtonHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

/**
 * The four buttons this app already had, named.
 *
 * Every variant below was extracted from styles already in use — the
 * problem wasn't missing buttons, it was the same button written three
 * ways (px-3 py-1 here, px-2.5 py-1 there) so controls drifted apart
 * depending on which file you opened.
 *
 * `className` still wins: cn() is twMerge, so a caller passing w-full or
 * a different padding overrides cleanly rather than emitting both.
 */

type Variant = 'solid' | 'ghost' | 'outline' | 'danger' | 'link'
type Size = 'xs' | 'sm'

const VARIANTS: Record<Variant, string> = {
  solid: 'bg-hive-accent-dim font-medium text-white hover:bg-hive-accent-dim/80',
  ghost: 'text-hive-muted hover:text-hive-text',
  outline:
    'border border-hive-border text-hive-muted hover:border-hive-accent hover:text-hive-text',
  danger: 'text-red-400 hover:bg-red-400/10',
  // Inline text actions ("show more", "edit"). Genuinely not the same
  // shape as the others — no padding, no rounding, it sits in a
  // sentence — so it carries no size and ignores SIZES.
  link: 'text-hive-muted hover:text-hive-text',
}

const SIZES: Record<Size, string> = {
  xs: 'px-3 py-1 text-xs',
  sm: 'px-3 py-1.5 text-sm',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  size?: Size
}

export function Button({
  variant = 'ghost',
  size = 'xs',
  className,
  type = 'button',
  ...props
}: ButtonProps) {
  return (
    <button
      type={type}
      className={cn(
        'transition-colors disabled:opacity-50',
        variant !== 'link' && 'rounded',
        VARIANTS[variant],
        variant !== 'link' && SIZES[size],
        className,
      )}
      {...props}
    />
  )
}
