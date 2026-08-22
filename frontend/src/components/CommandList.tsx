import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { cn } from '@/lib/utils'

interface Command {
  id: string
  name: string
  type: string
  response: string
  enabled: boolean
  use_count: number
}

interface CommandListProps {
  commands: Command[]
  selectedId: string | null
  onSelect: (id: string) => void
  onNew: () => void
}

const TYPE_LABELS: Record<string, string> = {
  text: 'text',
  lottery: 'lottery',
  random_list: 'random',
  counter: 'counter',
}

export function CommandList({ commands, selectedId, onSelect, onNew }: CommandListProps) {
  const [search, setSearch] = useState('')

  const filtered = commands.filter((cmd) => cmd.name.toLowerCase().includes(search.toLowerCase()))

  return (
    <div className="flex w-80 shrink-0 flex-col gap-2 overflow-hidden">
      <div className="flex items-center gap-2">
        <Input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search commands..."
          className="flex-1 px-3 py-1.5"
        />
        <Button variant="solid" size="sm" onClick={onNew}>
          + New
        </Button>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-px overflow-y-auto">
        {filtered.map((cmd) => (
          <button
            type="button"
            key={cmd.id}
            onClick={() => onSelect(cmd.id)}
            className={cn(
              'flex items-center gap-3 rounded px-3 py-2 text-left text-sm transition-colors',
              selectedId === cmd.id
                ? 'bg-hive-accent-dim/20 text-hive-text'
                : 'text-hive-muted hover:bg-hive-surface hover:text-hive-text',
              !cmd.enabled && 'opacity-50',
            )}>
            <span className="font-mono font-medium">!{cmd.name}</span>
            <span className="text-xs text-hive-muted">{TYPE_LABELS[cmd.type] ?? cmd.type}</span>
            <span className="ml-auto text-xs text-hive-muted">{cmd.use_count} uses</span>
          </button>
        ))}
        {filtered.length === 0 && (
          <p className="px-3 py-4 text-center text-sm text-hive-muted">
            {search ? 'No commands match your search.' : 'No commands yet.'}
          </p>
        )}
      </div>
    </div>
  )
}
