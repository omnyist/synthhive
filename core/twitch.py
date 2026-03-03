from __future__ import annotations

import logging

import httpx
from django.conf import settings

logger = logging.getLogger("bot")

TWITCH_API_BASE = "https://api.twitch.tv/helix"


async def twitch_request(
    channel,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response | None:
    """Make an authenticated Twitch API request using Synthfunc tokens.

    Fetches the channel owner's token from Synthfunc (source of truth).
    Falls back to the local cached token if Synthfunc is unreachable.
    On a 401, re-fetches from Synthfunc in case the token was refreshed
    by Synthfunc's TwitchIO and retries once.
    """
    from .synthfunc import get_token

    # Fetch token from Synthfunc, fall back to local cache
    token_data = await get_token(channel.twitch_channel_id)
    access_token = (
        token_data["access_token"] if token_data
        else channel.owner_access_token
    )

    if not access_token:
        return None

    headers = {
        "Authorization": f"Bearer {access_token}",
        "Client-Id": settings.TWITCH_CLIENT_ID,
    }
    kwargs.setdefault("headers", {}).update(headers)

    try:
        async with httpx.AsyncClient() as client:
            response = await client.request(method, url, **kwargs)

        if response.status_code != 401:
            return response

        # Token expired — re-fetch from Synthfunc (TwitchIO may have refreshed)
        logger.info(
            "Got 401 for #%s, re-fetching token from Synthfunc...",
            channel.twitch_channel_name,
        )

        fresh_token = await get_token(channel.twitch_channel_id)
        if not fresh_token:
            return None

        if fresh_token["access_token"] == access_token:
            # Synthfunc has the same stale token — nothing we can do
            logger.warning(
                "Synthfunc token is also stale for #%s",
                channel.twitch_channel_name,
            )
            return None

        kwargs["headers"]["Authorization"] = (
            f"Bearer {fresh_token['access_token']}"
        )

        async with httpx.AsyncClient() as client:
            return await client.request(method, url, **kwargs)

    except httpx.HTTPError:
        logger.exception(
            "HTTP error during Twitch request to %s for #%s",
            url,
            channel.twitch_channel_name,
        )
        return None
