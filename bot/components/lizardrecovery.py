"""Fires lizard timeouts orphaned by a bot restart.

A death's timeout is delivered after a theatrical delay held in an
in-memory asyncio sleep. When a deploy kills the process inside that
window, the death is already on the record but the ban never lands.
The play journals the pending ban in Redis before the countdown; at
startup this component fires any journaled ban that's still fresh —
late, but the lizard never forgets. Entries older than MAX_AGE are
dropped: a timeout arriving an hour later isn't justice, it's noise.
"""

from __future__ import annotations

import asyncio
import logging
import time

from asgiref.sync import sync_to_async
from twitchio.ext import commands

from bot import state

logger = logging.getLogger("bot")

STARTUP_DELAY = 15  # let the bot connect before shooting anyone
MAX_AGE = 600  # seconds past due before a journaled ban goes stale


class LizardRecovery(commands.Component):
    """Startup sweep: deliver pending timeouts from a previous process."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task | None = None

    async def component_load(self) -> None:
        self._task = asyncio.create_task(self._recover())

    async def component_teardown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _recover(self) -> None:
        try:
            await asyncio.sleep(STARTUP_DELAY)
            await self._sweep()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("[LizardRecovery] Sweep failed")

    async def _sweep(self) -> None:
        entries = await state.pending_timeouts_all()
        if not entries:
            return

        from core.models import Channel

        # The journal is shared across bot processes; only touch entries
        # for channels this bot runs — the other bot sweeps its own.
        channels = {
            c.twitch_channel_id: c
            for c in await sync_to_async(list)(
                Channel.objects.filter(
                    bot__twitch_user_id=self.bot.bot_id, is_active=True
                )
            )
        }

        from bot.skills import SKILL_REGISTRY

        handler = SKILL_REGISTRY["lizardroulette"]

        for entry in entries:
            channel = channels.get(entry["channel_id"])
            if channel is None:
                continue

            overdue = time.time() - entry["due_at"]
            if overdue > MAX_AGE:
                await state.pending_timeout_clear(
                    entry["channel_id"], entry["twitch_id"]
                )
                logger.info(
                    "[LizardRecovery] Dropped stale timeout: user=%s overdue=%ds",
                    entry["username"],
                    int(overdue),
                )
                continue

            delivered = await handler._timeout_user(
                channel,
                entry["channel_id"],
                entry["twitch_id"],
                entry["duration"],
            )
            if not delivered:
                # Leave the entry: it retries next restart and ages out
                # via MAX_AGE if the ban never goes through.
                logger.warning(
                    "[LizardRecovery] Timeout delivery failed: user=%s #%s",
                    entry["username"],
                    channel.twitch_channel_name,
                )
                continue

            await state.pending_timeout_clear(
                entry["channel_id"], entry["twitch_id"]
            )
            logger.info(
                "[LizardRecovery] Delivered late timeout: user=%s #%s overdue=%ds",
                entry["username"],
                channel.twitch_channel_name,
                int(overdue),
            )
            try:
                broadcaster = self.bot.create_partialuser(
                    user_id=channel.twitch_channel_id
                )
                await broadcaster.send_message(
                    sender=self.bot.bot_id,
                    message=(
                        f"LizardWithAGun The lizard never forgets. "
                        f"{entry['username']}, your timeout has been delivered."
                    ),
                )
            except Exception:
                logger.exception(
                    "[LizardRecovery] Failed to announce in #%s",
                    channel.twitch_channel_name,
                )
