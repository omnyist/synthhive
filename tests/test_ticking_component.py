from __future__ import annotations

import asyncio
import contextlib
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from bot.components.base import TickingComponent


class _Recorder(TickingComponent):
    """A minimal TickingComponent that records call order for one tick."""

    TICK_INTERVAL = 999  # never fires again within a test
    STARTUP_DELAY = 0

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self.calls: list[str] = []

    async def _tick_channel(self, channel_info: dict) -> None:
        self.calls.append(f"tick:{channel_info['name']}")


def _make_bot():
    bot = MagicMock()
    bot._channel_map = {"spoonee": {"name": "spoonee", "twitch_channel_id": "1"}}
    return bot


@pytest.mark.asyncio
async def test_tick_loop_releases_connection_before_ticking_any_channel():
    """The one guarantee this class exists to make structural rather than
    remembered: release_connection() runs before _tick_channel, every tick,
    for every subclass -- see bot/components/base.py.
    """
    component = _Recorder(_make_bot())

    with patch("bot.components.base.release_connection", new=AsyncMock()) as released:
        released.side_effect = lambda: component.calls.append("release")

        task = asyncio.create_task(component._tick_loop())
        await asyncio.sleep(0.05)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert component.calls == ["release", "tick:spoonee"]


@pytest.mark.asyncio
async def test_subclass_must_implement_tick_channel():
    """A subclass that forgets _tick_channel fails loudly rather than
    silently no-op'ing forever."""

    class Incomplete(TickingComponent):
        TICK_INTERVAL = 999
        STARTUP_DELAY = 0

    component = Incomplete(_make_bot())

    with pytest.raises(NotImplementedError):
        await component._tick_channel({"name": "spoonee"})
