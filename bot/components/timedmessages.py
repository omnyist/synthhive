"""Timed messages — posts scheduled messages while the stream is live.

Spoonee has wanted these back since Moobot, which sets the shape: an
interval plus a chat-activity gate, so the bot doesn't monologue at an
empty room.

Two rules keep it from being annoying, both learned from how these go
wrong elsewhere:

- **At most one message per channel per tick.** Several messages coming
  due together queue up instead of dumping into chat at once.
- **Live only, and the activity gate is checked at send time.** A quiet
  room means the message waits, not that it fires into silence.

Follows the CurrencyAccrual pattern: one background task, one pass per
channel per tick.
"""

from __future__ import annotations

import asyncio
import logging

from asgiref.sync import sync_to_async
from django.db.models import F
from django.utils import timezone
from twitchio.ext import commands

from core.twitch import TWITCH_API_BASE
from core.twitch import twitch_request

from .. import state
from ..variables import VariableContext
from ..variables import create_registry

logger = logging.getLogger("bot")

TICK_INTERVAL = 60


class TimedMessages(commands.Component):
    """Posts due timed messages while the broadcaster is live."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task | None = None
        self._registry = create_registry()
        self._channel_cache: dict[str, object] = {}

    async def component_load(self) -> None:
        self._task = asyncio.create_task(self._tick_loop())

    async def component_teardown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _tick_loop(self) -> None:
        try:
            await asyncio.sleep(20)  # let the bot finish connecting
            while True:
                for channel_info in self.bot._channel_map.values():
                    try:
                        await self._tick_channel(channel_info)
                    except Exception:
                        logger.exception(
                            "[TimedMessages] Error processing #%s",
                            channel_info["name"],
                        )
                await asyncio.sleep(TICK_INTERVAL)
        except asyncio.CancelledError:
            logger.info("[TimedMessages] Tick loop cancelled.")

    async def _get_channel(self, name: str):
        if name not in self._channel_cache:
            from core.models import Channel

            self._channel_cache[name] = await sync_to_async(
                Channel.objects.select_related("bot").get
            )(twitch_channel_name=name, is_active=True)
        return self._channel_cache[name]

    async def _is_live(self, channel, broadcaster_id: str) -> bool:
        response = await twitch_request(
            channel,
            "GET",
            f"{TWITCH_API_BASE}/streams",
            params={"user_id": broadcaster_id},
        )
        if response is None or response.status_code != 200:
            return False
        return bool(response.json().get("data", []))

    async def _tick_channel(self, channel_info: dict) -> None:
        from core.models import TimedMessage

        name = channel_info["name"]
        broadcaster_id = str(channel_info["twitch_channel_id"])

        # Cheapest check first: don't spend a Helix call on a channel
        # with nothing scheduled.
        enabled = await sync_to_async(list)(
            TimedMessage.objects.filter(
                channel__twitch_channel_name=name,
                channel__is_active=True,
                enabled=True,
            ).order_by("last_sent_at", "name")
        )
        if not enabled:
            return

        channel = await self._get_channel(name)
        if not await self._is_live(channel, broadcaster_id):
            return

        now = timezone.now()
        chat_lines = await state.chat_activity_get(broadcaster_id)

        # `last_sent_at` ascending means the longest-waiting message goes
        # first, so a backlog drains fairly instead of one row starving.
        due = next((m for m in enabled if m.is_due(now, chat_lines)), None)
        if due is None:
            return

        await self._send(due, channel_info, broadcaster_id, now)

    async def _send(self, timed, channel_info, broadcaster_id, now) -> None:
        from core.models import TimedMessage

        context = VariableContext(
            user=channel_info["name"],
            target=channel_info["name"],
            channel_name=channel_info["name"],
            broadcaster_id=broadcaster_id,
            command_name=timed.name,
            use_count=timed.use_count,
            raw_args="",
        )
        text = await self._registry.process(timed.message, context)

        message = text.strip()
        if not message:
            return
        # Same /me convention as command responses.
        if message.startswith("/me "):
            message = message[4:].lstrip("- ").strip()
            message = f"/me {message}"

        broadcaster = self.bot.create_partialuser(user_id=broadcaster_id)
        await broadcaster.send_message(sender=self.bot.bot_id, message=message)

        # Only recorded after the send actually succeeded — a failed
        # send should retry next tick, not silently consume its slot.
        await sync_to_async(
            TimedMessage.objects.filter(id=timed.id).update
        )(last_sent_at=now, use_count=F("use_count") + 1, updated_at=now)
        await state.chat_activity_reset(broadcaster_id)

        logger.info(
            "[TimedMessages] Sent %s to #%s", timed.name, channel_info["name"]
        )
