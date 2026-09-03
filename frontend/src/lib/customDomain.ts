import { api } from './api'

/**
 * Hosts that are always the dashboard, never a tenant's own domain.
 * Everything else is a candidate for /api/v1/public/domains/{host}/.
 *
 * A hardcoded list rather than an env var because this SPA has no
 * per-deploy config injection today (nothing else in frontend/ reads
 * one either) — add to this list, don't invent a config path for one
 * entry.
 */
const DASHBOARD_HOSTS = new Set(['bots.bardsaders.com', 'localhost', '127.0.0.1'])

/**
 * If this request arrived on a tenant's own domain (e.g. spoonee.tv),
 * resolve which channel it serves. Returns null on the dashboard host,
 * on a lookup failure, or when the domain isn't configured — in every
 * "null" case the caller falls through to ordinary browser routing, so
 * an unconfigured or unreachable host never breaks the app, only
 * declines to rewrite it.
 */
export async function resolveCustomDomain(hostname: string): Promise<string | null> {
  if (DASHBOARD_HOSTS.has(hostname)) return null
  try {
    const { channel_slug } = await api<{ channel_slug: string }>(
      `/api/v1/public/domains/${encodeURIComponent(hostname)}/`,
    )
    return channel_slug
  } catch {
    return null
  }
}
