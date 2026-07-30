import { useQuery } from '@tanstack/react-query'
import {
  createRootRoute,
  Link,
  Outlet,
  useMatchRoute,
  useRouterState,
} from '@tanstack/react-router'
import { api } from '@/lib/api'
import { cn } from '@/lib/utils'

interface ChannelBrief {
  id: string
  name: string
  bot_name: string
}

interface MeResponse {
  twitch_id: string
  twitch_username: string
  twitch_display_name: string
  twitch_avatar: string
  is_staff: boolean
  channels: ChannelBrief[]
}

export const Route = createRootRoute({
  component: RootLayout,
})

// Dashboard sections under /$channelSlug/ — anything else in that
// position is a public event page (e.g. /spoonee/awesome-august-2026).
const DASHBOARD_SECTIONS = new Set(['commands', 'counters', 'aliases', 'event'])

function isPublicPath(pathname: string): boolean {
  if (pathname.startsWith('/overlay/')) return true
  const parts = pathname.split('/').filter(Boolean)
  return parts.length === 2 && !DASHBOARD_SECTIONS.has(parts[1])
}

function RootLayout() {
  const pathname = useRouterState({ select: (s) => s.location.pathname })

  // Public routes (OBS browser sources, shareable event pages) get no
  // session, no chrome — and crucially no /me query, whose 401
  // redirect would bounce anonymous visitors into OAuth.
  if (isPublicPath(pathname)) {
    return <Outlet />
  }

  return <DashboardLayout />
}

function DashboardLayout() {
  const { data: user } = useQuery<MeResponse>({
    queryKey: ['me'],
    queryFn: () => api<MeResponse>('/api/v1/me'),
    retry: false,
  })

  if (!user) {
    return <Outlet />
  }

  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar user={user} />
      <main className="flex flex-1 flex-col overflow-hidden">
        <Outlet />
      </main>
    </div>
  )
}

function Sidebar({ user }: { user: MeResponse }) {
  const matchRoute = useMatchRoute()
  const currentChannel = user.channels.length > 0 ? user.channels[0] : null
  const isCommands = currentChannel
    ? matchRoute({ to: '/$channelSlug/commands', params: { channelSlug: currentChannel.name } })
    : false
  const isCounters = currentChannel
    ? matchRoute({ to: '/$channelSlug/counters', params: { channelSlug: currentChannel.name } })
    : false
  const isAliases = currentChannel
    ? matchRoute({ to: '/$channelSlug/aliases', params: { channelSlug: currentChannel.name } })
    : false
  const isEvent = currentChannel
    ? matchRoute({ to: '/$channelSlug/event', params: { channelSlug: currentChannel.name } })
    : false
  const isInvites = matchRoute({ to: '/invites' })

  return (
    <aside className="flex w-48 flex-col border-r border-hive-border bg-hive-surface">
      <div className="border-b border-hive-border px-4 py-3">
        <h1 className="text-sm font-bold tracking-tight text-hive-text">Synthhive</h1>
      </div>
      <nav className="flex flex-1 flex-col gap-1 p-2">
        {currentChannel && (
          <>
            <Link
              to="/$channelSlug/commands"
              params={{ channelSlug: currentChannel.name }}
              className={cn(
                'rounded px-3 py-1.5 text-sm transition-colors',
                isCommands
                  ? 'bg-hive-accent-dim/20 text-hive-text'
                  : 'text-hive-muted hover:text-hive-text',
              )}>
              Commands
            </Link>
            <Link
              to="/$channelSlug/counters"
              params={{ channelSlug: currentChannel.name }}
              className={cn(
                'rounded px-3 py-1.5 text-sm transition-colors',
                isCounters
                  ? 'bg-hive-accent-dim/20 text-hive-text'
                  : 'text-hive-muted hover:text-hive-text',
              )}>
              Counters
            </Link>
            <Link
              to="/$channelSlug/aliases"
              params={{ channelSlug: currentChannel.name }}
              className={cn(
                'rounded px-3 py-1.5 text-sm transition-colors',
                isAliases
                  ? 'bg-hive-accent-dim/20 text-hive-text'
                  : 'text-hive-muted hover:text-hive-text',
              )}>
              Aliases
            </Link>
            <Link
              to="/$channelSlug/event"
              params={{ channelSlug: currentChannel.name }}
              className={cn(
                'rounded px-3 py-1.5 text-sm transition-colors',
                isEvent
                  ? 'bg-hive-accent-dim/20 text-hive-text'
                  : 'text-hive-muted hover:text-hive-text',
              )}>
              Event
            </Link>
          </>
        )}
        {user.is_staff && (
          <Link
            to="/invites"
            className={cn(
              'rounded px-3 py-1.5 text-sm transition-colors',
              isInvites
                ? 'bg-hive-accent-dim/20 text-hive-text'
                : 'text-hive-muted hover:text-hive-text',
            )}>
            Invites
          </Link>
        )}
      </nav>
      <div className="border-t border-hive-border p-3">
        <div className="flex items-center gap-2">
          {user.twitch_avatar && (
            <img src={user.twitch_avatar} alt="" className="h-6 w-6 rounded-full" />
          )}
          <span className="flex-1 truncate text-xs text-hive-text">{user.twitch_display_name}</span>
        </div>
        <a
          href="/auth/logout/"
          className="mt-2 block text-xs text-hive-muted transition-colors hover:text-hive-text">
          Logout
        </a>
      </div>
    </aside>
  )
}
