import type { InputHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

/**
 * Text inputs. The base string here appeared verbatim 5 times, with two
 * near-identical cousins differing only in background and padding —
 * accidental variation, not design.
 *
 * `mono` is a real distinction (command names, counter keys) so it's a
 * prop. Width stays a caller concern: forms size fields to their content
 * (w-32 for a number, w-64 for a label), and that's deliberate.
 */

const BASE =
  'rounded border border-hive-border bg-hive-surface px-2 py-1 text-sm ' +
  'text-hive-text placeholder-hive-muted focus:border-hive-accent focus:outline-none'

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  mono?: boolean
}

export function Input({ mono, className, ...props }: InputProps) {
  return <input className={cn(BASE, mono && 'font-mono', className)} {...props} />
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  mono?: boolean
}

export function Textarea({ mono, className, ...props }: TextareaProps) {
  return <textarea className={cn(BASE, mono && 'font-mono', className)} {...props} />
}
