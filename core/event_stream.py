"""Server-sent events stream for the dashboard's Event page.

Synthfunc already publishes every campaign moment to Redis pub/sub —
gift arrivals (campaign:update), bid war allocations (campaign:bidwar),
milestone unlocks, timer changes. This view forwards that channel to
the browser as SSE so the pending-gift queue and standings update the
moment something happens, instead of on a polling interval. SSE (not
WebSocket) because the dashboard only needs server→client push: all
mutations already go through the REST API, and EventSource reconnects
itself.
"""

from __future__ import annotations

import hmac
import json
import logging

import redis.asyncio as aioredis
from asgiref.sync import sync_to_async
from django.conf import settings
from django.http import HttpRequest
from django.http import JsonResponse
from django.http import StreamingHttpResponse

logger = logging.getLogger("bot")

HEARTBEAT_SECONDS = 25  # keep Cloudflare/Daphne idle timeouts at bay


async def campaign_stream(request: HttpRequest, channel_slug: str):
    """SSE stream of campaign events for a channel the user owns."""
    user = await request.auser()
    if not user.is_authenticated:
        return JsonResponse({"detail": "Not authenticated"}, status=401)

    from .models import Channel
    from .models import TwitchProfile

    try:
        profile = await sync_to_async(TwitchProfile.objects.get)(user=user)
    except TwitchProfile.DoesNotExist:
        return JsonResponse({"detail": "No Twitch profile"}, status=403)

    channel = await sync_to_async(
        Channel.objects.filter(
            twitch_channel_name=channel_slug,
            twitch_channel_id=profile.twitch_id,
            is_active=True,
        ).first
    )()
    if channel is None:
        return JsonResponse({"detail": "Channel not found"}, status=404)

    response = StreamingHttpResponse(
        _event_generator(channel_slug),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


async def overlay_stream(request: HttpRequest, channel_slug: str):
    """SSE stream of campaign events, gated by the channel's overlay
    key instead of a session — for OBS browser-source widgets."""
    from .models import Channel

    key = request.GET.get("key", "")
    channel = await sync_to_async(
        Channel.objects.filter(
            twitch_channel_name=channel_slug, is_active=True
        ).first
    )()
    if (
        channel is None
        or not key
        or not hmac.compare_digest(str(channel.overlay_key), key.lower())
    ):
        return JsonResponse({"detail": "Invalid overlay key."}, status=403)

    response = StreamingHttpResponse(
        _event_generator(channel_slug),
        content_type="text/event-stream",
    )
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response


async def _event_generator(channel_slug: str):
    """Forward Redis campaign events as SSE, with heartbeats."""
    client = aioredis.from_url(settings.REDIS_URL)
    pubsub = client.pubsub()
    try:
        await pubsub.subscribe(f"events:{channel_slug}:campaign")
        yield ": connected\n\n"

        while True:
            message = await pubsub.get_message(
                ignore_subscribe_messages=True, timeout=HEARTBEAT_SECONDS
            )
            if message is None:
                yield ": ping\n\n"
                continue

            event_type = "campaign:update"
            try:
                data = json.loads(message["data"])
                event_type = data.get("event_type", event_type)
            except (ValueError, TypeError, KeyError):
                pass

            yield f"data: {json.dumps({'event_type': event_type})}\n\n"
    finally:
        try:
            await pubsub.aclose()
            await client.aclose()
        except Exception:
            logger.debug("Error closing SSE Redis connection", exc_info=True)
