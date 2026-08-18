"""Refunds dungeon wagers orphaned by a bot restart.

Dungeon wagers are debited immediately, but the game that pays winners
lives in an in-memory asyncio task. When a deploy or crash kills the
process mid-game, the debits survive and the game doesn't. At startup
this component finds journal rows still pending from before this
process started, refunds the principal via Synthfunc, and says so in
chat.
"""

from __future__ import annotations

import asyncio
import logging

from asgiref.sync import sync_to_async
from django.utils import timezone
from twitchio.ext import commands

from core.synthfunc import transact_wallets

logger = logging.getLogger("bot")

STARTUP_DELAY = 15  # let the bot connect before announcing refunds


class DungeonRecovery(commands.Component):
    """Startup sweep: refund pending wagers from a previous process."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._task: asyncio.Task | None = None
        # Only wagers from before this process are orphans — a game that
        # starts while we're sleeping must not have its wagers refunded.
        self._cutoff = timezone.now()

    async def component_load(self) -> None:
        self._task = asyncio.create_task(self._recover())

    async def component_teardown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _recover(self) -> None:
        try:
            await asyncio.sleep(STARTUP_DELAY)

            from core.models import Channel

            channels = await sync_to_async(list)(
                Channel.objects.filter(
                    bot__twitch_user_id=self.bot.bot_id, is_active=True
                )
            )
            for channel in channels:
                try:
                    await self._recover_channel(channel)
                except Exception:
                    logger.exception(
                        "[DungeonRecovery] Error recovering #%s",
                        channel.twitch_channel_name,
                    )
        except asyncio.CancelledError:
            pass

    async def _recover_channel(self, channel) -> None:
        from core.models import DungeonWager

        wagers = await sync_to_async(list)(
            DungeonWager.objects.filter(
                channel=channel,
                status=DungeonWager.Status.PENDING,
                created_at__lt=self._cutoff,
            )
        )
        if not wagers:
            return

        entries = [
            {
                "twitch_id": w.twitch_id,
                "amount": str(w.wager),
                "username": w.twitch_username,
                "display_name": w.display_name,
            }
            for w in wagers
        ]
        result = await transact_wallets(
            channel.twitch_channel_name,
            entries,
            reason="dungeon_refund",
            # Independent refunds; the caller reads `failed` per id to
            # decide which wagers stay pending for the next sweep.
            best_effort=True,
        )
        if result is None:
            logger.warning(
                "[DungeonRecovery] Refund transact failed for #%s — "
                "wagers stay pending, retried next restart",
                channel.twitch_channel_name,
            )
            return

        failed_ids = {f.get("twitch_id") for f in result.get("failed", [])}
        refunded = []
        for w in wagers:
            if w.twitch_id in failed_ids:
                continue
            await sync_to_async(
                DungeonWager.objects.filter(
                    pk=w.pk, status=DungeonWager.Status.PENDING
                ).update
            )(status=DungeonWager.Status.REFUNDED, resolved_at=timezone.now())
            refunded.append(w)

        if not refunded:
            return

        logger.info(
            "[DungeonRecovery] Refunded %d wager(s) in #%s",
            len(refunded),
            channel.twitch_channel_name,
        )

        names = ", ".join(f"{w.display_name} ({w.wager})" for w in refunded)
        message = (
            "The dungeon collapsed while the party was inside — "
            f"everyone stumbles back to town with their wagers: {names}"
        )
        try:
            broadcaster = self.bot.create_partialuser(
                user_id=channel.twitch_channel_id
            )
            await broadcaster.send_message(
                sender=self.bot.bot_id, message=message
            )
        except Exception:
            logger.exception(
                "[DungeonRecovery] Failed to announce refunds in #%s",
                channel.twitch_channel_name,
            )
