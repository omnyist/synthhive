from __future__ import annotations

import asyncio
import logging
from datetime import timedelta

import twitchio
from channels.db import aclose_old_connections
from django.utils import timezone
from synthlib.django.heartbeat import abeat_liveness as beat_liveness
from twitchio import eventsub
from twitchio import web
from twitchio.ext import commands

from .components.accrual import CurrencyAccrual
from .components.ads import AdAnnounce
from .components.dungeonrecovery import DungeonRecovery
from .components.errors import ErrorHandler
from .components.lizardbullets import LizardBullets
from .components.lizardrecovery import LizardRecovery
from .components.management import ManagementCommands
from .components.timedmessages import TimedMessages
from .heartbeat import worker_id
from .router import CommandRouter
from .state import get_client

logger = logging.getLogger("bot")


class BotClient(commands.Bot):
    """TwitchIO bot that reads commands from the Django database.

    Each BotClient instance represents one bot identity (e.g., Elsydeon)
    connected to one or more channels.
    """

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        bot_id: str,
        bot_name: str,
        token: str,
        refresh_token: str,
        channels: list[dict],
        port: int = 4343,
    ) -> None:
        self.bot_name = bot_name
        self._channel_map = {ch["name"]: ch for ch in channels}

        adapter = web.AiohttpAdapter(port=port)
        super().__init__(
            client_id=client_id,
            client_secret=client_secret,
            bot_id=bot_id,
            prefix="!",
            adapter=adapter,
        )

        self._initial_token = token
        self._initial_refresh = refresh_token

    async def setup_hook(self) -> None:
        await self.add_token(self._initial_token, self._initial_refresh)

        subscribed = 0
        total = len(self._channel_map)
        for channel_info in self._channel_map.values():
            broadcaster_id = channel_info["twitch_channel_id"]
            payload = eventsub.ChatMessageSubscription(
                broadcaster_user_id=broadcaster_id,
                user_id=self.bot_id,
            )
            try:
                await self.subscribe_websocket(payload=payload)
                subscribed += 1
                logger.info(
                    "[%s] Subscribed to chat in #%s",
                    self.bot_name,
                    channel_info["name"],
                )
            except Exception:
                logger.exception(
                    "[%s] Failed to subscribe to #%s",
                    self.bot_name,
                    channel_info["name"],
                )

        await self.add_component(ErrorHandler(self))
        await self.add_component(ManagementCommands(self))
        await self.add_component(CommandRouter(self))
        await self.add_component(CurrencyAccrual(self))
        await self.add_component(AdAnnounce(self))
        await self.add_component(LizardBullets(self))
        await self.add_component(DungeonRecovery(self))
        await self.add_component(LizardRecovery(self))
        await self.add_component(TimedMessages(self))

        self._health_task = asyncio.create_task(
            self._subscription_health_check()
        )

        logger.info(
            "[%s] Setup complete. subscribed=%d/%d",
            self.bot_name,
            subscribed,
            total,
        )

    async def event_ready(self) -> None:
        logger.info("[%s] Bot is ready (ID: %s).", self.bot_name, self.bot_id)

    async def before_invoke(self, ctx: commands.Context) -> None:
        """Release this thread's DB connection before every framework command.

        TwitchIO's own `commands.Bot.event_message` dispatches `!addcom`,
        `!count`, and the rest of ManagementCommands' `@commands.command`
        handlers through `process_commands()` -- a SEPARATE `event_message`
        listener from `CommandRouter`'s, scheduled as its own
        `asyncio.create_task` by `Client.dispatch()` with no ordering
        relative to CommandRouter's. Calling `aclose_old_connections()` only
        in CommandRouter (router.py:105) therefore never runs on this path at
        all; a mod typing `!addcom` right after a synthcore Postgres recreate
        could still hit the dead connection CommandRouter was supposed to
        have already cleared. `before_invoke` is the framework's own
        single choke point for every registered command across every
        Component, present and future, so the fix belongs here once rather
        than in each of ManagementCommands' handlers by hand.
        """
        await aclose_old_connections()

    async def event_token_refreshed(
        self, payload: twitchio.TokenRefreshedPayload
    ) -> None:
        """Persist refreshed bot token back to the database."""
        from asgiref.sync import sync_to_async

        from core.models import Bot as BotModel

        if str(payload.user_id) != str(self.bot_id):
            logger.debug(
                "[%s] Ignoring token refresh for user %s (not this bot).",
                self.bot_name,
                payload.user_id,
            )
            return

        try:
            bot = await sync_to_async(BotModel.objects.get)(
                twitch_user_id=self.bot_id,
            )
            bot.access_token = payload.token
            bot.refresh_token = payload.refresh_token
            bot.token_expires_at = timezone.now() + timedelta(
                seconds=payload.expires_in
            )
            await sync_to_async(bot.save)(
                update_fields=[
                    "access_token",
                    "refresh_token",
                    "token_expires_at",
                ]
            )
            logger.info(
                "[%s] Refreshed bot token saved to DB.",
                self.bot_name,
            )
        except BotModel.DoesNotExist:
            logger.warning(
                "[%s] Bot record not found for token refresh (id=%s).",
                self.bot_name,
                self.bot_id,
            )
        except Exception:
            logger.exception(
                "[%s] Failed to persist refreshed bot token.",
                self.bot_name,
            )

    async def _subscription_health_check(self) -> None:
        """Every minute, re-create any chat subscription Twitch says is gone."""
        try:
            await asyncio.sleep(30)

            while True:
                await asyncio.sleep(60)

                try:
                    await self._check_subscriptions_once()
                except Exception:
                    logger.exception(
                        "[%s] Subscription health check error",
                        self.bot_name,
                    )

        except asyncio.CancelledError:
            pass

    async def _enabled_chat_channels(self) -> set[str] | None:
        """Broadcaster ids this bot has an enabled chat subscription for, per Twitch.

        Asked of Twitch, not read from self._websockets. On a reconnect,
        TwitchIO's welcome handler replaces the whole socket map with the
        reconnecting socket, dropping the others without closing them. Those
        sockets keep receiving chat, so the map could say "missing" while chat
        was still arriving. Re-subscribing on that word opened another socket
        each time. By 2026-09-23 Elsydeon held at least three sockets
        re-creating the same #avalonstar subscription, and Twitch answered each
        extra one with 429.

        Only this process holds this bot's user token, so an enabled
        subscription means some socket here is receiving. None when Twitch
        can't be asked: unknown is not missing, and treating it as missing
        would re-subscribe on an API blip.
        """
        try:
            result = await self.fetch_eventsub_subscriptions(
                token_for=self.bot_id, type="channel.chat.message"
            )
            enabled: set[str] = set()
            async for sub in result.subscriptions:
                condition = sub.condition or {}
                ours = str(condition.get("user_id")) == str(self.bot_id)
                if sub.status == "enabled" and ours:
                    enabled.add(str(condition.get("broadcaster_user_id")))
            return enabled
        except Exception:
            logger.warning(
                "[%s] Could not list chat subscriptions from Twitch; skipping this check.",
                self.bot_name,
                exc_info=True,
            )
            return None

    async def _check_subscriptions_once(self) -> None:
        active = await self._enabled_chat_channels()
        if active is None:
            return

        expected = {
            str(info["twitch_channel_id"]) for info in self._channel_map.values()
        }

        # Beat only on Twitch's word that chat is subscribed. It used to beat
        # on the in-memory socket map, which could hold a subscription Twitch
        # had already dropped.
        if active & expected:
            await beat_liveness(worker_id(self.bot_name), client=get_client())

        missing = expected - active
        if not missing:
            return

        # Close dead websockets (0 subscriptions) so subscribe_websocket
        # creates a fresh connection instead of reusing the stale session.
        await self._close_dead_websockets()

        for channel_info in self._channel_map.values():
            bid = str(channel_info["twitch_channel_id"])
            if bid not in missing:
                continue

            payload = eventsub.ChatMessageSubscription(
                broadcaster_user_id=bid,
                user_id=self.bot_id,
            )
            try:
                await self.subscribe_websocket(payload=payload)
                logger.info(
                    "[%s] Re-subscribed to chat in #%s",
                    self.bot_name,
                    channel_info["name"],
                )
            except Exception:
                logger.exception(
                    "[%s] Failed to re-subscribe to #%s",
                    self.bot_name,
                    channel_info["name"],
                )

    async def _close_dead_websockets(self) -> None:
        """Close websockets that lost all their subscriptions."""
        for token_for, sockets in list(self._websockets.items()):
            for session_id, ws in list(sockets.items()):
                if ws.subscription_count == 0:
                    logger.info(
                        "[%s] Closing dead websocket session %s",
                        self.bot_name,
                        session_id,
                    )
                    try:
                        await ws.close()
                    except Exception:
                        pass
                    sockets.pop(session_id, None)
            if not sockets:
                self._websockets.pop(token_for, None)
