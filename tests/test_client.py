from __future__ import annotations

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
