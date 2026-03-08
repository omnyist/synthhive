"""Lizard bullet loader — silently loads the lizard's revolver on a timer."""

from __future__ import annotations

import asyncio
import logging
import random

from twitchio.ext import commands

from bot.skills import SKILL_REGISTRY

logger = logging.getLogger("bot")

TICK_INTERVAL = 30  # seconds
BULLET_ODDS = 651  # 1-in-651 per tick
CHAMBER_COUNT = 6


class LizardBullets(commands.Component):
    """Silently loads the lizard's revolver on a background timer.

    Every 30 seconds, rolls a 1/651 chance per channel to load all 6
    chambers. When loaded, the next 6 uses of !lizardroulette are
    guaranteed losses. No announcement — happens in complete silence.
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task | None = None

    async def component_load(self) -> None:
        self._task = asyncio.create_task(self._tick_loop())

    async def component_teardown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _tick_loop(self) -> None:
        """Roll for bullet loading forever, sleeping between ticks."""
        try:
            await asyncio.sleep(10)  # wait for bot to fully connect
            while True:
                for channel_info in self.bot._channel_map.values():
                    try:
                        self._tick_channel(channel_info)
                    except Exception:
                        logger.exception(
                            "[LizardBullets] Error processing #%s",
                            channel_info["name"],
                        )
                await asyncio.sleep(TICK_INTERVAL)
        except asyncio.CancelledError:
            logger.info("[LizardBullets] Tick loop cancelled.")

    def _tick_channel(self, channel_info: dict) -> None:
        """Roll once for a single channel."""
        if random.randint(1, BULLET_ODDS) != 1:
            return

        handler = SKILL_REGISTRY.get("lizardroulette")
        if handler is None:
            return

        broadcaster_id = channel_info["twitch_channel_id"]
        handler._bullets[broadcaster_id] = CHAMBER_COUNT
        logger.info(
            "[LizardBullets] Gun loaded in #%s",
            channel_info["name"],
        )
