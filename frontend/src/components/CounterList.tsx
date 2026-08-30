import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { List, ListEmpty, ListRow } from '@/components/ui/List'

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
      <List>
        {filtered.map((counter) => (
          <ListRow
            key={counter.id}
            selected={selectedId === counter.id}
            onClick={() => onSelect(counter.id)}>
            <span className="font-mono font-medium">{counter.name}</span>
            {counter.label && <span className="text-xs text-hive-muted">{counter.label}</span>}
            <span className="ml-auto font-mono text-xs text-hive-muted">{counter.value}</span>
          </ListRow>
        ))}
        {filtered.length === 0 && (
          <ListEmpty>{search ? 'No counters match your search.' : 'No counters yet.'}</ListEmpty>
        )}
      </List>
    </div>
  )
}
