import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import {
  createMemoryHistory,
  createRouter,
  type RouterHistory,
  RouterProvider,
} from '@tanstack/react-router'
import { StrictMode } from 'react'
import ReactDOM from 'react-dom/client'
import { resolveCustomDomain } from '@/lib/customDomain'
import { routeTree } from './routeTree.gen'

import './index.css'

declare module '@tanstack/react-router' {
  interface Register {
    router: ReturnType<typeof createRouter<typeof routeTree>>
  }
}

const queryClient = new QueryClient()

/**
 * On a tenant's own domain, the URL bar shows their domain and root
 * path (spoonee.tv/awesome-august-2026) while the app internally needs
 * to route as /{channel}/awesome-august-2026 — every existing public
 * route, unmodified. A memory history carries that internal path
 * without ever touching window.location, so the address bar stays the
 * tenant's own domain and back/forward still work within the app.
 *
 * On the dashboard host (or an unrecognised/unconfigured domain) this
 * resolves to null and the router uses ordinary browser history, i.e.
 * today's behaviour, unchanged.
 */
async function buildHistory(): Promise<RouterHistory | undefined> {
  const channelSlug = await resolveCustomDomain(window.location.hostname)
  if (!channelSlug) return undefined
  return createMemoryHistory({
    initialEntries: [`/${channelSlug}${window.location.pathname}${window.location.search}`],
  })
}

async function main() {
  const history = await buildHistory()
  const router = createRouter({ routeTree, ...(history ? { history } : {}) })

  const rootElement = document.getElementById('root')!
  if (!rootElement.innerHTML) {
    const root = ReactDOM.createRoot(rootElement)
    root.render(
      <StrictMode>
        <QueryClientProvider client={queryClient}>
          <RouterProvider router={router} />
        </QueryClientProvider>
      </StrictMode>,
    )
  }
}

main()
