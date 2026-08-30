import { useState } from 'react'
import { Button } from '@/components/ui/Button'
import { Input } from '@/components/ui/Input'
import { List, ListEmpty, ListRow } from '@/components/ui/List'

interface Alias {
  id: string
  name: string
  target: string
}

interface AliasListProps {
  aliases: Alias[]
  selectedId: string | null
  onSelect: (id: string) => void
  onNew: () => void
}

export function AliasList({ aliases, selectedId, onSelect, onNew }: AliasListProps) {
  const [search, setSearch] = useState('')

  const filtered = aliases.filter(
    (a) =>
      a.name.toLowerCase().includes(search.toLowerCase()) ||
      a.target.toLowerCase().includes(search.toLowerCase()),
  )

  return (
    <div className="flex w-80 shrink-0 flex-col gap-2 overflow-hidden">
      <div className="flex items-center gap-2">
        <Input
          type="text"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder="Search aliases..."
          className="flex-1 px-3 py-1.5"
        />
        <Button variant="solid" size="sm" onClick={onNew}>
          + New
        </Button>
      </div>
      <List>
        {filtered.map((alias) => (
          <ListRow
            key={alias.id}
            selected={selectedId === alias.id}
            onClick={() => onSelect(alias.id)}
            className="gap-2">
            <span className="font-mono font-medium">!{alias.name}</span>
            <span className="text-xs text-hive-muted">&rarr;</span>
            <span className="font-mono text-xs text-hive-muted">!{alias.target}</span>
          </ListRow>
        ))}
        {filtered.length === 0 && (
          <ListEmpty>{search ? 'No aliases match your search.' : 'No aliases yet.'}</ListEmpty>
        )}
      </List>
    </div>
  )
}
