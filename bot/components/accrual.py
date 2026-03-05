"""Currency accrual — awards points to chatters while the stream is live."""

from __future__ import annotations

import asyncio
import logging

from asgiref.sync import sync_to_async
from twitchio.ext import commands

from core.synthfunc import accrue_wallets
from core.twitch import TWITCH_API_BASE
from core.twitch import twitch_request

logger = logging.getLogger("bot")

TICK_INTERVAL = 300  # 5 minutes
AMOUNT = "1.0"
MINUTES_PER_TICK = 5


class CurrencyAccrual(commands.Component):
    """Awards currency to chatters while the stream is live."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task | None = None
        self._channel_cache: dict[str, object] = {}

    async def component_load(self) -> None:
        self._task = asyncio.create_task(self._tick_loop())

    async def component_teardown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _tick_loop(self) -> None:
        """Run accrual ticks forever, sleeping between each."""
        try:
            await asyncio.sleep(10)  # wait for bot to fully connect
            while True:
                for channel_info in self.bot._channel_map.values():
                    try:
                        await self._tick_channel(channel_info)
                    except Exception:
                        logger.exception(
                            "[Accrual] Error processing #%s",
                            channel_info["name"],
                        )
                await asyncio.sleep(TICK_INTERVAL)
        except asyncio.CancelledError:
            logger.info("[Accrual] Tick loop cancelled.")

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

    async def _fetch_chatters(
        self, channel, broadcaster_id: str
    ) -> list[dict]:
        """Fetch all chatters from the Twitch Helix API."""
        chatters = []
        cursor = None

        while True:
            params = {
                "broadcaster_id": broadcaster_id,
                "moderator_id": broadcaster_id,
                "first": 1000,
            }
            if cursor:
                params["after"] = cursor

            response = await twitch_request(
                channel,
                "GET",
                f"{TWITCH_API_BASE}/chat/chatters",
                params=params,
            )
            if response is None or response.status_code != 200:
                break

            body = response.json()
            for chatter in body.get("data", []):
                chatters.append(
                    {
                        "twitch_id": chatter["user_id"],
                        "username": chatter["user_login"],
                        "display_name": chatter["user_name"],
                    }
                )

            cursor = body.get("pagination", {}).get("cursor")
            if not cursor:
                break

        return chatters

    async def _tick_channel(self, channel_info: dict) -> None:
        """Run one accrual tick for a single channel."""
        broadcaster_id = channel_info["twitch_channel_id"]
        tenant_slug = channel_info["name"]
        channel = await self._get_channel(channel_info)

        if not await self._is_live(channel, broadcaster_id):
            return

        chatters = await self._fetch_chatters(channel, broadcaster_id)
        if not chatters:
            return

        result = await accrue_wallets(
            tenant_slug=tenant_slug,
            chatters=chatters,
            amount=AMOUNT,
            minutes=MINUTES_PER_TICK,
        )

        if result:
            logger.info(
                "[Accrual] #%s: %d chatters, %d wallets updated.",
                tenant_slug,
                len(chatters),
                result.get("updated", 0),
            )
