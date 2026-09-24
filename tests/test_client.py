from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from unittest.mock import patch

import pytest

from bot.client import BotClient


@pytest.mark.asyncio
async def test_before_invoke_releases_the_connection():
    """TwitchIO's own command framework (ManagementCommands' !addcom, !count,
    etc.) dispatches through commands.Bot.event_message -- a SEPARATE
    asyncio.create_task from CommandRouter's, per Client.dispatch(). Nothing
    in CommandRouter's aclose_old_connections() call runs on that path.
    before_invoke is the framework's one hook that runs for every registered
    command regardless of which Component defined it, so it's the only place
    this can be verified without exercising a live command end-to-end.
    """
    bot = BotClient.__new__(BotClient)

    with patch("bot.client.aclose_old_connections", new=AsyncMock()) as released:
        await bot.before_invoke(ctx=object())

    released.assert_awaited_once()


# ---------------------------------------------------------------------------
# Subscription health: Twitch's word, not TwitchIO's socket map
# ---------------------------------------------------------------------------

BOT_ID = "66977097"
AVALONSTAR = "38981465"


class _Subs:
    def __init__(self, subs):
        self._subs = subs

    def __aiter__(self):
        async def gen():
            for s in self._subs:
                yield s

        return gen()


def _sub(broadcaster, status="enabled", user=BOT_ID):
    return SimpleNamespace(
        status=status,
        condition={"broadcaster_user_id": broadcaster, "user_id": user},
    )


def _bot(twitch_subs=None, fetch_error=None):
    bot = BotClient.__new__(BotClient)
    bot.bot_name = "Elsydeon"
    bot._bot_id = BOT_ID
    bot._channel_map = {
        "avalonstar": {"name": "avalonstar", "twitch_channel_id": AVALONSTAR}
    }

    async def fetch(*, token_for, type):
        assert token_for == BOT_ID and type == "channel.chat.message"
        if fetch_error:
            raise fetch_error
        return SimpleNamespace(subscriptions=_Subs(twitch_subs or []))

    bot.fetch_eventsub_subscriptions = fetch
    bot.subscribe_websocket = AsyncMock()
    bot._close_dead_websockets = AsyncMock()
    return bot


@pytest.mark.asyncio
async def test_an_enabled_subscription_on_twitch_is_left_alone():
    """The 2026-09-23 case: TwitchIO's socket map had lost the socket holding
    the subscription, but Twitch still delivered to it. Re-subscribing on the
    map's word is what piled up duplicate sockets and 429s."""
    bot = _bot([_sub(AVALONSTAR)])
    with (
        patch("bot.client.beat_liveness", new=AsyncMock()) as beat,
        patch("bot.client.get_client"),
    ):
        await bot._check_subscriptions_once()
    bot.subscribe_websocket.assert_not_awaited()
    bot._close_dead_websockets.assert_not_awaited()
    beat.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_subscription_twitch_does_not_have_is_recreated():
    bot = _bot([])
    with (
        patch("bot.client.beat_liveness", new=AsyncMock()) as beat,
        patch("bot.client.get_client"),
    ):
        await bot._check_subscriptions_once()
    bot._close_dead_websockets.assert_awaited_once()
    bot.subscribe_websocket.assert_awaited_once()
    beat.assert_not_awaited()


@pytest.mark.asyncio
async def test_disabled_or_foreign_subscriptions_do_not_count():
    bot = _bot(
        [
            _sub(AVALONSTAR, status="websocket_disconnected"),
            _sub(AVALONSTAR, user="someone-else"),
        ]
    )
    with (
        patch("bot.client.beat_liveness", new=AsyncMock()),
        patch("bot.client.get_client"),
    ):
        await bot._check_subscriptions_once()
    bot.subscribe_websocket.assert_awaited_once()


@pytest.mark.asyncio
async def test_twitch_unreachable_is_unknown_not_missing():
    bot = _bot(fetch_error=ConnectionError("helix down"))
    with (
        patch("bot.client.beat_liveness", new=AsyncMock()) as beat,
        patch("bot.client.get_client"),
    ):
        await bot._check_subscriptions_once()
    bot.subscribe_websocket.assert_not_awaited()
    bot._close_dead_websockets.assert_not_awaited()
    beat.assert_not_awaited()
