"""Async client for Synthfunc's REST API.

Provides typed functions for each Synthfunc endpoint that the bot
needs — quotes, campaigns, members, and stream status.

Usage:
    from core.synthfunc import get_random_quote, search_quotes

    quote = await get_random_quote()
    results = await search_quotes("fish")
"""

from __future__ import annotations

import logging
from typing import Any

import httpx
from django.conf import settings

logger = logging.getLogger("bot")

# Tracks whether Synthfunc is unreachable to suppress log spam.
# First failure logs a warning; subsequent failures are silent until recovery.
_synthfunc_down: bool = False


def _headers() -> dict[str, str]:
    return {"X-API-Key": settings.SYNTHFUNC_API_KEY}


def _mark_recovered() -> None:
    """Log recovery if Synthfunc was previously unreachable."""
    global _synthfunc_down
    if _synthfunc_down:
        logger.info("Synthfunc connection recovered")
        _synthfunc_down = False


def _mark_down(exc: Exception, url_path: str) -> None:
    """Log first network failure, suppress subsequent."""
    global _synthfunc_down
    if not _synthfunc_down:
        logger.warning(
            "Synthfunc unreachable (%s) for %s — suppressing until recovery",
            type(exc).__name__,
            url_path,
        )
        _synthfunc_down = True


async def _get(
    path: str,
    params: dict[str, Any] | None = None,
    tenant_slug: str | None = None,
) -> dict | list | None:
    """Make a GET request to Synthfunc."""
    url_path = f"/{tenant_slug}{path}" if tenant_slug else path
    try:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{settings.SYNTHFUNC_API_URL}{url_path}",
                headers=_headers(),
                params=params,
                timeout=10.0,
            )

        _mark_recovered()

        if response.status_code == 404:
            return None

        if response.status_code != 200:
            logger.error(
                "Synthfunc GET %s failed: %s %s",
                url_path,
                response.status_code,
                response.text,
            )
            return None

        return response.json()

    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        _mark_down(exc, url_path)
        return None

    except httpx.HTTPError:
        logger.exception("HTTP error during Synthfunc GET %s", url_path)
        return None


async def _post(
    path: str, data: dict[str, Any], tenant_slug: str | None = None
) -> dict | None:
    """Make a POST request to Synthfunc."""
    url_path = f"/{tenant_slug}{path}" if tenant_slug else path
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{settings.SYNTHFUNC_API_URL}{url_path}",
                headers=_headers(),
                json=data,
                timeout=10.0,
            )

        _mark_recovered()

        if response.status_code not in (200, 201):
            logger.error(
                "Synthfunc POST %s failed: %s %s",
                url_path,
                response.status_code,
                response.text,
            )
            return None

        return response.json()

    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        _mark_down(exc, url_path)
        return None

    except httpx.HTTPError:
        logger.exception("HTTP error during Synthfunc POST %s", url_path)
        return None


# --- Quotes ---


async def get_random_quote(tenant_slug: str) -> dict | None:
    """Get a single random quote."""
    result = await _get("/quotes/random", {"limit": 1}, tenant_slug=tenant_slug)
    if result and isinstance(result, list) and len(result) > 0:
        return result[0]
    return None


async def get_quote_by_number(number: int, tenant_slug: str) -> dict | None:
    """Get a specific quote by its number."""
    return await _get(f"/quotes/{number}", tenant_slug=tenant_slug)


async def search_quotes(
    query: str, tenant_slug: str, limit: int = 5, random: bool = False
) -> dict | None:
    """Search quotes by text. Returns {quotes: [...], total_matches: int}."""
    return await _get(
        "/quotes/search",
        {"q": query, "limit": limit, "random": random},
        tenant_slug=tenant_slug,
    )


async def get_quotes_by_user(
    username: str, tenant_slug: str, limit: int = 5, random: bool = False
) -> dict | None:
    """Get quotes by a specific user. Returns {quotes: [...], total_matches: int}."""
    return await _get(
        f"/quotes/by-user/{username}",
        {"limit": limit, "random": random},
        tenant_slug=tenant_slug,
    )


async def get_latest_quote(tenant_slug: str) -> dict | None:
    """Get the most recent quote."""
    result = await _get("/quotes/latest", {"limit": 1}, tenant_slug=tenant_slug)
    if result and isinstance(result, list) and len(result) > 0:
        return result[0]
    return None


async def get_quote_stats(username: str, tenant_slug: str) -> dict | None:
    """Get quote statistics for a user."""
    return await _get(f"/quotes/stats/{username}", tenant_slug=tenant_slug)


async def create_quote(
    text: str,
    quotee_username: str,
    quoter_username: str,
    tenant_slug: str,
    game: str | None = None,
) -> dict | None:
    """Create a new quote."""
    data = {
        "text": text,
        "quotee_username": quotee_username,
        "quoter_username": quoter_username,
    }
    if game:
        data["game"] = game
    return await _post("/quotes/", data, tenant_slug=tenant_slug)


# --- Wallets ---


async def accrue_wallets(
    tenant_slug: str,
    chatters: list[dict],
    amount: str = "1.0",
    minutes: int = 5,
) -> dict | None:
    """Bulk-increment balance and minutes for a list of chatters."""
    return await _post(
        "/wallets/accrue",
        {"chatters": chatters, "amount": amount, "minutes": minutes},
        tenant_slug=tenant_slug,
    )


async def transact_wallets(
    tenant_slug: str,
    entries: list[dict],
    reason: str = "",
) -> dict | None:
    """Process a batch of debits and credits against wallets."""
    return await _post(
        "/wallets/transact",
        {"entries": entries, "reason": reason},
        tenant_slug=tenant_slug,
    )


async def get_wallet(
    twitch_id: str, tenant_slug: str, username: str | None = None
) -> dict | None:
    """Get a wallet by Twitch ID, with optional username for reconciliation."""
    params = {"username": username} if username else None
    return await _get(f"/wallets/{twitch_id}", params, tenant_slug=tenant_slug)


async def get_wallet_leaderboard(
    tenant_slug: str, limit: int = 10, sort_by: str = "balance"
) -> list | None:
    """Get top wallets by balance or minutes."""
    return await _get(
        "/wallets/leaderboard",
        {"limit": limit, "sort_by": sort_by},
        tenant_slug=tenant_slug,
    )


# --- Events ---


async def get_chat_messages(
    tenant_slug: str, limit: int = 50000
) -> list[str] | None:
    """Fetch chat message texts from Synthfunc for Markov chain building."""
    result = await _get(
        "/events/messages", {"limit": limit}, tenant_slug=tenant_slug
    )
    if result is None:
        return None
    return result.get("messages", [])


# --- Campaigns ---


async def get_active_campaign(tenant_slug: str) -> dict | None:
    """Get the currently active campaign with metrics and milestones."""
    return await _get("/campaigns/active", tenant_slug=tenant_slug)


async def start_campaign_timer(tenant_slug: str) -> dict | None:
    """Start or restart the subathon timer for the active campaign."""
    return await _post("/campaigns/timer/start", {}, tenant_slug=tenant_slug)


async def pause_campaign_timer(tenant_slug: str) -> dict | None:
    """Pause the subathon timer for the active campaign."""
    return await _post("/campaigns/timer/pause", {}, tenant_slug=tenant_slug)


async def get_campaign_metrics(campaign_id: str, tenant_slug: str) -> dict | None:
    """Get metrics for a specific campaign."""
    return await _get(
        f"/campaigns/{campaign_id}/metrics", tenant_slug=tenant_slug
    )


async def get_gift_leaderboard(tenant_slug: str, limit: int = 10) -> list | None:
    """Get the gift leaderboard for the active campaign."""
    return await _get(
        "/campaigns/active/gifts/leaderboard",
        {"limit": limit},
        tenant_slug=tenant_slug,
    )


# --- Members ---


async def get_member(twitch_id: str) -> dict | None:
    """Get or create a member by Twitch ID."""
    return await _get(f"/members/{twitch_id}")


async def create_member(
    display_name: str,
    username: str | None = None,
    twitch_id: str | None = None,
) -> dict | None:
    """Create a new member."""
    data: dict[str, Any] = {"display_name": display_name}
    if username:
        data["username"] = username
    if twitch_id:
        data["twitch_id"] = twitch_id
    return await _post("/members/", data)


# --- Ads ---


async def enable_ads(tenant_slug: str) -> dict | None:
    """Enable the ad rotation scheduler."""
    return await _post("/ads/enable", {}, tenant_slug=tenant_slug)


async def disable_ads(tenant_slug: str) -> dict | None:
    """Disable the ad rotation scheduler."""
    return await _post("/ads/disable", {}, tenant_slug=tenant_slug)


async def get_ads_status(tenant_slug: str) -> dict | None:
    """Get the current ad scheduler status and config."""
    return await _get("/ads/status", tenant_slug=tenant_slug)


# --- Streams ---


async def get_stream_status(tenant_slug: str) -> dict | None:
    """Get current broadcaster stream status."""
    return await _get("/streams/status/", tenant_slug=tenant_slug)


# --- Tokens ---


async def _patch(
    path: str, data: dict[str, Any], tenant_slug: str | None = None
) -> dict | None:
    """Make a PATCH request to Synthfunc."""
    url_path = f"/{tenant_slug}{path}" if tenant_slug else path
    try:
        async with httpx.AsyncClient() as client:
            response = await client.patch(
                f"{settings.SYNTHFUNC_API_URL}{url_path}",
                headers=_headers(),
                json=data,
                timeout=10.0,
            )

        _mark_recovered()

        if response.status_code != 200:
            logger.error(
                "Synthfunc PATCH %s failed: %s %s",
                url_path,
                response.status_code,
                response.text,
            )
            return None

        return response.json()

    except (httpx.ConnectError, httpx.TimeoutException) as exc:
        _mark_down(exc, url_path)
        return None


async def get_bid_wars(
    tenant_slug: str, status: str | None = None
) -> list | None:
    """List bid wars on the tenant's active campaign."""
    params = {"status": status} if status else None
    return await _get("/campaigns/bidwars/", params=params, tenant_slug=tenant_slug)


async def create_bid_war(
    tenant_slug: str, title: str, options: list[str]
) -> dict | None:
    """Create a bid war with its options on the active campaign."""
    return await _post(
        "/campaigns/bidwars/",
        {"title": title, "options": options},
        tenant_slug=tenant_slug,
    )


async def set_bid_war_status(
    tenant_slug: str, bid_war_id: str, status: str
) -> dict | None:
    """Open or close a bid war."""
    return await _patch(
        f"/campaigns/bidwars/{bid_war_id}",
        {"status": status},
        tenant_slug=tenant_slug,
    )


async def allocate_bid_war_points(
    tenant_slug: str, bid_war_id: str, option_id: str, points: int, note: str = ""
) -> dict | None:
    """Append a point allocation (negative = correction)."""
    return await _post(
        f"/campaigns/bidwars/{bid_war_id}/allocations/",
        {"option_id": option_id, "points": points, "note": note},
        tenant_slug=tenant_slug,
    )


async def get_bid_war_allocations(
    tenant_slug: str, bid_war_id: str, limit: int = 50
) -> list | None:
    """Most-recent-first allocation history."""
    return await _get(
        f"/campaigns/bidwars/{bid_war_id}/allocations/",
        params={"limit": limit},
        tenant_slug=tenant_slug,
    )


async def ensure_tenant(
    slug: str,
    name: str,
    twitch_id: str,
    twitch_username: str,
) -> dict | None:
    """Idempotently provision a Synthfunc tenant for a channel.

    Without a tenant, every Synthfunc integration for the channel
    silently 404s — accrual, wallets, quotes, and (critically) token
    custody. Called at invite completion and by `syncsynthfunc`.
    """
    return await _post(
        "/tenants/ensure",
        {
            "slug": slug,
            "name": name,
            "twitch_id": twitch_id,
            "twitch_username": twitch_username,
        },
    )


async def save_token(
    user_id: str,
    access_token: str,
    refresh_token: str | None = None,
    expires_in: int = 3600,
) -> dict | None:
    """Push an OAuth token to Synthfunc for centralized storage."""
    return await _post(
        "/authentication/tokens/",
        {
            "user_id": user_id,
            "access_token": access_token,
            "refresh_token": refresh_token,
            "expires_in": expires_in,
        },
    )


async def get_token(user_id: str) -> dict | None:
    """Fetch an OAuth token from Synthfunc."""
    return await _get(f"/authentication/tokens/{user_id}")
