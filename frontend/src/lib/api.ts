// Shape of a Ninja `@paginate` response (LimitOffsetPagination default).
export interface Paginated<T> {
  items: T[]
  count: number
}

function getCookie(name: string): string | null {
  const value = `; ${document.cookie}`
  const parts = value.split(`; ${name}=`)
  if (parts.length === 2) return decodeURIComponent(parts.pop()!.split(';')[0])
  return null
}

export async function api<T>(path: string, options: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  }

  const method = options.method ?? 'GET'

  if (method !== 'GET' && method !== 'HEAD') {
    headers['Content-Type'] ??= 'application/json'
    const csrfToken = getCookie('csrftoken')
    if (csrfToken) {
      headers['X-CSRFToken'] = csrfToken
    }
  }

  const res = await fetch(path, { ...options, headers, credentials: 'same-origin' })

  if (res.status === 401) {
    window.location.href = '/auth/twitch/login/'
    throw new Error('Not authenticated')
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}))
    throw new Error(body.detail || `Request failed: ${res.status}`)
  }

  if (res.status === 204) return undefined as T

  return res.json()
}

// Fetch every page of a `@paginate` endpoint and return the flattened items.
// The default page size is 100; this walks `offset` until `count` is reached so
// list views never silently truncate to the first page.
export async function fetchAll<T>(path: string): Promise<T[]> {
  const sep = path.includes('?') ? '&' : '?'
  const first = await api<Paginated<T>>(path)
  const items = [...first.items]
  while (items.length < first.count) {
    const page = await api<Paginated<T>>(`${path}${sep}offset=${items.length}`)
    if (page.items.length === 0) break
    items.push(...page.items)
  }
  return items
}
