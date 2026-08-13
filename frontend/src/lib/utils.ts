import { type ClassValue, clsx } from 'clsx'
import { twMerge } from 'tailwind-merge'

/**
 * Merge class names, letting later arguments win conflicts.
 *
 * The previous implementation just joined the strings, so an override
 * like cn(baseWithTextSm, 'text-xs') emitted both and left the winner
 * to Tailwind's stylesheet order rather than the caller's intent.
 */
export const cn = (...inputs: ClassValue[]) => twMerge(clsx(inputs))
