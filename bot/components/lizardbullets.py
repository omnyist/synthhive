"""Lizard bullet loader — silently loads the lizard's revolver on a timer."""

from __future__ import annotations

import logging
import random

from asgiref.sync import sync_to_async
from synthlib.django.heartbeat import awrite
from twitchio.ext import commands

from bot import state
from core.twitch import TWITCH_API_BASE
from core.twitch import twitch_request

from ..heartbeat import worker_id
from .base import TickingComponent

logger = logging.getLogger("bot")

BULLET_ODDS = 651  # 1-in-651 per tick
CHAMBER_COUNT = 6


class LizardBullets(TickingComponent):
    """Silently loads the lizard's revolver on a background timer.

    Every 30 seconds, rolls a 1/651 chance per channel to load all 6
    chambers. When loaded, the next 6 uses of !lizardroulette are
    guaranteed losses. No announcement — happens in complete silence.
    Only ticks while the channel is live.
    """

    TICK_INTERVAL = 30  # seconds

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)
        self._channel_cache: dict[str, object] = {}

    async def _get_channel(self, channel_info: dict) -> object:
        """Load and cache the Django Channel model for twitch_request."""
        name = channel_info["name"]
        if name not in self._channel_cache:
            from core.models import Channel

            channel = await sync_to_async(
                Channel.objects.select_related("bot").get
            )(twitch_channel_name=name, is_active=True)
            self._channel_cache[name] = channel
        return self._channel_cache[name]

    async def _is_live(self, channel, broadcaster_id: str) -> bool:
        """Check if the broadcaster is currently live."""
        response = await twitch_request(
            channel,
            "GET",
            f"{TWITCH_API_BASE}/streams",
            params={"user_id": broadcaster_id},
        )
        if response is None or response.status_code != 200:
            return False
        data = response.json().get("data", [])
        return len(data) > 0

    async def _tick_channel(self, channel_info: dict) -> None:
        """Roll once for a single channel, only if live and bullets enabled."""
        broadcaster_id = channel_info["twitch_channel_id"]
        channel = await self._get_channel(channel_info)

        from core.models import Skill

        try:
            skill = await sync_to_async(Skill.objects.get)(
                channel=channel,
                name="lizardroulette",
            )
            if not skill.config.get("bullets_enabled", True):
                return
        except Skill.DoesNotExist:
            return

        if not await self._is_live(channel, broadcaster_id):
            return

        # Same free observation as accrual's, on a 30s tick rather than 5min,
        # so the live gate stays fresh for channels running this skill.
        await awrite(worker_id(self.bot.bot_name), "live", client=state.get_client())

        if random.randint(1, BULLET_ODDS) != 1:
            return

        await state.bullets_set(broadcaster_id, CHAMBER_COUNT)
        logger.info(
            "[LizardBullets] Gun loaded in #%s",
            channel_info["name"],
        )
