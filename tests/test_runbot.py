"""Tests for runbot's per-attempt client rebuilding."""

from __future__ import annotations

from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from bot.management.commands.runbot import Command

CFG = {
    "bot_id": "1",
    "bot_name": "TestBot",
    "token": "t",
    "refresh_token": "r",
    "channels": [],
}


class TestRunBotRetries:
    async def test_fresh_client_per_attempt(self):
        """Regression: retrying start() on the same TwitchIO client
        after a failed attempt comes up "ready" but deaf (power-outage
        boot, 2026-08-09). Every attempt must construct a new client
        and close the dead one."""
        first = MagicMock()
        first.start = AsyncMock(side_effect=ConnectionError("dns down"))
        first.close = AsyncMock()
        second = MagicMock()
        second.start = AsyncMock(return_value=None)

        command = Command()
        with (
            patch.object(Command, "_build_client", side_effect=[first, second]) as build,
            patch("asyncio.sleep", new_callable=AsyncMock),
        ):
            await command._run_bot(CFG, 4343)

        assert build.call_count == 2
        first.start.assert_awaited_once()
        first.close.assert_awaited_once()
        second.start.assert_awaited_once()

    async def test_cancellation_propagates(self):
        import asyncio

        client = MagicMock()
        client.start = AsyncMock(side_effect=asyncio.CancelledError)

        command = Command()
        with patch.object(Command, "_build_client", return_value=client):
            with pytest.raises(asyncio.CancelledError):
                await command._run_bot(CFG, 4343)
