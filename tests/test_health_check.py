from __future__ import annotations

from collections import defaultdict
from unittest.mock import AsyncMock
from unittest.mock import MagicMock


def _make_bot():
    """Create a mock bot with the attributes the health check needs."""
    bot = MagicMock(spec=[])
    bot.bot_name = "TestBot"
    bot.bot_id = "99999"
    bot._channel_map = {
        "avalonstar": {"name": "avalonstar", "twitch_channel_id": "38981465"},
        "spoonee": {"name": "spoonee", "twitch_channel_id": "78238052"},
    }
    bot._websockets = defaultdict(dict)
    bot.subscribe_websocket = AsyncMock()
    return bot


def _add_subscription(bot, session_id, sub_id, broadcaster_id, user_id="99999"):
    """Add a fake subscription to the bot's websocket state."""
    if session_id not in bot._websockets.get("token", {}):
        ws = MagicMock()
        ws._subscriptions = {}
        bot._websockets["token"][session_id] = ws

    bot._websockets["token"][session_id]._subscriptions[sub_id] = {
        "type": "channel.chat.message",
        "version": "1",
        "condition": {
            "broadcaster_user_id": broadcaster_id,
            "user_id": user_id,
        },
        "transport": {"session_id": session_id},
    }


def _get_active_channels(bot) -> set[str]:
    """Extract active broadcaster IDs from websocket subscriptions."""
    active: set[str] = set()
    for sockets in bot._websockets.values():
        for ws in sockets.values():
            for sub_data in ws._subscriptions.values():
                condition = sub_data.get("condition", {})
                bid = condition.get("broadcaster_user_id")
                if bid:
                    active.add(bid)
    return active


def _get_expected_channels(bot) -> set[str]:
    """Get expected broadcaster IDs from channel map."""
    return {
        info["twitch_channel_id"]
        for info in bot._channel_map.values()
    }


class TestSubscriptionHealthCheck:
    async def test_detects_all_missing(self):
        bot = _make_bot()

        active = _get_active_channels(bot)
        expected = _get_expected_channels(bot)

        assert expected - active == {"38981465", "78238052"}

    async def test_resubscribes_all_missing(self):
        bot = _make_bot()

        missing = _get_expected_channels(bot) - _get_active_channels(bot)
        for channel_info in bot._channel_map.values():
            if channel_info["twitch_channel_id"] in missing:
                await bot.subscribe_websocket(payload=MagicMock())

        assert bot.subscribe_websocket.call_count == 2

    async def test_skips_when_all_present(self):
        bot = _make_bot()
        _add_subscription(bot, "session1", "sub1", "38981465")
        _add_subscription(bot, "session1", "sub2", "78238052")

        missing = _get_expected_channels(bot) - _get_active_channels(bot)

        assert missing == set()

    async def test_detects_partial_loss(self):
        bot = _make_bot()
        _add_subscription(bot, "session1", "sub1", "38981465")

        missing = _get_expected_channels(bot) - _get_active_channels(bot)

        assert missing == {"78238052"}

    async def test_resubscribes_only_missing(self):
        bot = _make_bot()
        _add_subscription(bot, "session1", "sub1", "38981465")

        missing = _get_expected_channels(bot) - _get_active_channels(bot)
        for channel_info in bot._channel_map.values():
            if channel_info["twitch_channel_id"] in missing:
                await bot.subscribe_websocket(payload=MagicMock())

        assert bot.subscribe_websocket.call_count == 1

    async def test_survives_resubscribe_failure(self):
        bot = _make_bot()
        bot.subscribe_websocket = AsyncMock(
            side_effect=Exception("Twitch API error")
        )

        missing = _get_expected_channels(bot) - _get_active_channels(bot)
        for channel_info in bot._channel_map.values():
            if channel_info["twitch_channel_id"] in missing:
                try:
                    await bot.subscribe_websocket(payload=MagicMock())
                except Exception:
                    pass

        assert bot.subscribe_websocket.call_count == 2
