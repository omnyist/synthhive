import { useMutation, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/Button'
import { ConfirmDialog } from '@/components/ui/Dialog'
import { Field } from '@/components/ui/Field'
import { Input } from '@/components/ui/Input'
import { api } from '@/lib/api'

interface Counter {
  id: string
  name: string
  label: string
  value: number
}

interface CounterFormProps {
  channelSlug: string
  counter: Counter | null
  onClose: () => void
  onSaved: () => void
}

interface FormState {
  name: string
  label: string
  value: number
}

function initialState(counter: Counter | null): FormState {
  if (counter) {
    return {
      name: counter.name,
      label: counter.label,
      value: counter.value,
    }
  }
  return {
    name: '',
    label: '',
    value: 0,
  }
}

export function CounterForm({ channelSlug, counter, onClose, onSaved }: CounterFormProps) {
  const queryClient = useQueryClient()
  const [form, setForm] = useState<FormState>(() => initialState(counter))
  const [error, setError] = useState<string | null>(null)
  const [confirmingDelete, setConfirmingDelete] = useState(false)
  const isNew = !counter

  useEffect(() => {
    setForm(initialState(counter))
    setError(null)
  }, [counter])

  const saveMutation = useMutation({
    mutationFn: async () => {
      const body = { ...form }

      if (isNew) {
        return api(`/api/v1/counters/channels/${channelSlug}/`, {
          method: 'POST',
          body: JSON.stringify(body),
        })
      }

      return api(`/api/v1/counters/${counter.id}/`, {
        method: 'PATCH',
        body: JSON.stringify(body),
      })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['counters', channelSlug] })
      onSaved()
    },
    onError: (err: Error) => {
      setError(err.message)
    },
  })

  const deleteMutation = useMutation({
    mutationFn: () => api(`/api/v1/counters/${counter!.id}/`, { method: 'DELETE' }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['counters', channelSlug] })
      onClose()
    },
    onError: (err: Error) => {
      setError(err.message)
    },
  })

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) => {
    setForm((prev) => ({ ...prev, [key]: value }))
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto border-l border-hive-border pl-4">
      <div className="flex items-center justify-between">
        <h3 className="text-sm font-medium">
          {isNew ? 'New Counter' : `Editing: ${counter.name}`}
        </h3>
        <div className="flex items-center gap-2">
          {!isNew && (
            <Button
              variant="danger"
              onClick={() => {
                setConfirmingDelete(true)
              }}
              disabled={deleteMutation.isPending}>
              Delete
            </Button>
          )}
          <Button onClick={onClose}>Cancel</Button>
          <Button
            variant="solid"
            onClick={() => saveMutation.mutate()}
            disabled={saveMutation.isPending}>
            {saveMutation.isPending ? 'Saving...' : 'Save'}
          </Button>
        </div>
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <Field label="Name">
        <Input
          mono
          type="text"
          value={form.name}
          onChange={(e) => update('name', e.target.value)}
          placeholder="counter_name"
          pattern="[a-zA-Z0-9_]+"
          className="w-48"
        />
      </Field>

      <Field label="Label">
        <Input
          type="text"
          value={form.label}
          onChange={(e) => update('label', e.target.value)}
          placeholder="Display label (e.g. Death Count)"
          className="w-64"
        />
      </Field>

      <Field label="Value">
        <Input
          mono
          type="number"
          value={form.value}
          onChange={(e) => update('value', parseInt(e.target.value, 10) || 0)}
          className="w-32"
        />
      </Field>
      {counter && (
        <ConfirmDialog
          open={confirmingDelete}
          onClose={() => setConfirmingDelete(false)}
          onConfirm={() => deleteMutation.mutate()}
          title="Delete counter?"
          body={
            <>
              The counter <span className="font-mono text-hive-text">{counter.name}</span> and its
              value will be removed.
            </>
          }
        />
      )}
    </div>
  )
}
