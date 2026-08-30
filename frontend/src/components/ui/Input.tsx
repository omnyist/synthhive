import type { InputHTMLAttributes, SelectHTMLAttributes, TextareaHTMLAttributes } from 'react'
import { cn } from '@/lib/utils'

/**
 * Text inputs. The base string appeared verbatim 5 times, with cousins
 * differing only in background and padding — accidental variation.
 *
 * Two props, both real distinctions rather than tidying:
 *
 * `mono` — command names, counter keys, anything the user reads as an
 * identifier.
 *
 * `inset` — a darker fill for fields sitting *inside* a surface panel,
 * where the default bg-hive-surface would disappear into its own
 * background. EventEditor and the invite-link field had both invented
 * this locally.
 *
 * Width stays a caller concern: forms size fields to their content
 * (w-32 for a number, w-64 for a label), and that's deliberate.
 */

const BASE =
  'rounded border border-hive-border px-2 py-1 text-sm ' +
  'text-hive-text placeholder-hive-muted focus:border-hive-accent focus:outline-none'

const tone = (inset?: boolean) => (inset ? 'bg-hive-dark' : 'bg-hive-surface')

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  mono?: boolean
  inset?: boolean
}

export function Input({ mono, inset, className, ...props }: InputProps) {
  return <input className={cn(BASE, tone(inset), mono && 'font-mono', className)} {...props} />
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  mono?: boolean
  inset?: boolean
}

export function Textarea({ mono, inset, className, ...props }: TextareaProps) {
  return <textarea className={cn(BASE, tone(inset), mono && 'font-mono', className)} {...props} />
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  inset?: boolean
}

/** Same field styling as Input — a select is a field, not a button. */
export function Select({ inset, className, ...props }: SelectProps) {
  return <select className={cn(BASE, tone(inset), className)} {...props} />
}
