import * as Headless from '@headlessui/react'
import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'
import { Button } from './Button'

/**
 * Modal dialog, on Headless UI.
 *
 * This is the one component where hand-rolling and getting it right
 * diverge sharply: focus has to be trapped inside the panel, Escape has
 * to close, focus has to return to whatever opened it, and the page
 * behind must not scroll. Headless UI does all of that and the ARIA
 * wiring; the styling below is ours.
 *
 * Adapted from the Catalyst dialog in nyxsis-panel, retinted to hive
 * tokens and with the size scale cut to what this app actually opens.
 */

export function Dialog({
  open,
  onClose,
  children,
  className,
}: {
  open: boolean
  onClose: () => void
  children: ReactNode
  className?: string
}) {
  return (
    <Headless.Dialog open={open} onClose={onClose} className="relative z-50">
      <Headless.DialogBackdrop
        transition
        className="fixed inset-0 bg-black/60 transition duration-100 data-closed:opacity-0 data-enter:ease-out data-leave:ease-in"
      />
      <div className="fixed inset-0 flex w-screen items-center justify-center p-4">
        <Headless.DialogPanel
          transition
          className={cn(
            'w-full max-w-md rounded-lg border border-hive-border bg-hive-surface p-5 shadow-xl',
            'transition duration-100 data-closed:translate-y-2 data-closed:opacity-0 data-enter:ease-out data-leave:ease-in',
            className,
          )}>
          {children}
        </Headless.DialogPanel>
      </div>
    </Headless.Dialog>
  )
}

export function DialogTitle({ children }: { children: ReactNode }) {
  return (
    <Headless.DialogTitle className="text-sm font-medium text-hive-text">
      {children}
    </Headless.DialogTitle>
  )
}

export function DialogBody({ children }: { children: ReactNode }) {
  return <div className="mt-2 text-sm text-hive-muted">{children}</div>
}

export function DialogActions({ children }: { children: ReactNode }) {
  return <div className="mt-5 flex justify-end gap-2">{children}</div>
}

/**
 * The shape every destructive action in this app needed. It replaced
 * seven window.confirm() calls, which worked but were native browser
 * chrome in the middle of a styled panel — and which block the whole
 * tab while open.
 */
export function ConfirmDialog({
  open,
  onClose,
  onConfirm,
  title,
  body,
  confirmLabel = 'Delete',
  danger = true,
}: {
  open: boolean
  onClose: () => void
  onConfirm: () => void
  title: string
  body?: ReactNode
  confirmLabel?: string
  danger?: boolean
}) {
  return (
    <Dialog open={open} onClose={onClose}>
      <DialogTitle>{title}</DialogTitle>
      {body && <DialogBody>{body}</DialogBody>}
      <DialogActions>
        <Button onClick={onClose}>Cancel</Button>
        <Button
          variant={danger ? 'danger' : 'solid'}
          onClick={() => {
            onConfirm()
            onClose()
          }}>
          {confirmLabel}
        </Button>
      </DialogActions>
    </Dialog>
  )
}
