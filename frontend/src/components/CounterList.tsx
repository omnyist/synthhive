import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { cn } from '@/lib/utils'

interface Counter {
  id: string
  name: string
  label: string
  value: number
}

interface CounterListProps {
  counters: Counter[]
  selectedId: string | null
  onSelect: (id: string) => void
  onNew: () => void
}

export function CounterList({ counters, selectedId, onSelect, onNew }: CounterListProps) {
  const [search, setSearch] = useState('')

  const filtered = counters.filter((c) => c.name.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="flex w-80 shrink-0 flex-col gap-2 overflow-hidden">
      <div className="flex items-center gap-2">
        <Input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search counters..."
          className="flex-1 px-3 py-1.5"
        />
        <Button variant="solid" size="sm" onClick={onNew}>
          + New
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-px overflow-y-auto">
        {filtered.map((counter) => (
          <button
            type="button"
            key={counter.id}
            onClick={() => onSelect(counter.id)}
            className={cn(
              'flex items-center gap-3 rounded px-3 py-2 text-left text-sm transition-colors',
              selectedId === counter.id
                ? 'bg-hive-accent-dim/20 text-hive-text'
                : 'text-hive-muted hover:bg-hive-surface hover:text-hive-text',
            )}>
            <span className="font-mono font-medium">{counter.name}</span>
            {counter.label && <span className="text-xs text-hive-muted">{counter.label}</span>}
            <span className="ml-auto font-mono text-xs text-hive-muted">{counter.value}</span>
          </button>
        ))}
        {filtered.length === 0 && (
          <p className="px-3 py-4 text-center text-sm text-hive-muted">
            {search ? 'No counters match your search.' : 'No counters yet.'}
          </p>
        )}
      </div>
    </div>
  )
}
