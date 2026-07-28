import { useQueryClient } from '@tanstack/react-query'
import { useEffect } from 'react'

/**
 * Subscribe to the channel's campaign SSE stream and invalidate the
 * event-page queries whenever anything happens server-side — a gift
 * arrives, an allocation lands, a milestone unlocks. EventSource
 * reconnects on its own; polling remains only as a slow backstop.
 */
export function useCampaignStream(channelSlug: string) {
  const queryClient = useQueryClient()

  useEffect(() => {
    const source = new EventSource(`/api/v1/events/channels/${channelSlug}/stream`)

    source.onmessage = () => {
      queryClient.invalidateQueries({ queryKey: ['campaigns', channelSlug] })
      queryClient.invalidateQueries({ queryKey: ['campaign', channelSlug] })
      queryClient.invalidateQueries({ queryKey: ['gifters', channelSlug] })
      queryClient.invalidateQueries({ queryKey: ['bidwars', channelSlug] })
      queryClient.invalidateQueries({ queryKey: ['bidwar-allocations', channelSlug] })
      queryClient.invalidateQueries({ queryKey: ['pending-gifts', channelSlug] })
    }

    return () => source.close()
  }, [channelSlug, queryClient])
}
