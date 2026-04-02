from __future__ import annotations

import asyncio
import logging

import twitchio
from twitchio import eventsub
from twitchio import web
from twitchio.ext import commands

from .components.accrual import CurrencyAccrual
from .components.ads import AdAnnounce
from .components.errors import ErrorHandler
from .components.lizardbullets import LizardBullets
from .components.management import ManagementCommands
from .router import CommandRouter

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

        for channel_info in self._channel_map.values():
            broadcaster_id = channel_info["twitch_channel_id"]
            payload = eventsub.ChatMessageSubscription(
                broadcaster_user_id=broadcaster_id,
                user_id=self.bot_id,
            )
            try:
                await self.subscribe_websocket(payload=payload)
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

        self._health_task = asyncio.create_task(
            self._subscription_health_check()
        )

        logger.info("[%s] Setup complete.", self.bot_name)

    async def event_ready(self) -> None:
        logger.info("[%s] Bot is ready (ID: %s).", self.bot_name, self.bot_id)

    async def _subscription_health_check(self) -> None:
        """Periodically verify EventSub subscriptions and re-create missing ones.

        TwitchIO silently drops subscriptions that fail to resubscribe after
        a WebSocket reconnect. This task detects the loss and re-subscribes.
        """
        try:
            await asyncio.sleep(30)

            while True:
                await asyncio.sleep(60)

                try:
                    active_channels: set[str] = set()
                    for sockets in self._websockets.values():
                        for ws in sockets.values():
                            for sub_data in ws._subscriptions.values():
                                condition = sub_data.get("condition", {})
                                bid = condition.get("broadcaster_user_id")
                                if bid:
                                    active_channels.add(bid)

                    expected = {
                        info["twitch_channel_id"]
                        for info in self._channel_map.values()
                    }
                    missing = expected - active_channels

                    if not missing:
                        continue

                    # Close dead websockets (0 subscriptions) so
                    # subscribe_websocket creates a fresh connection
                    # instead of reusing the stale session.
                    await self._close_dead_websockets()

                    for channel_info in self._channel_map.values():
                        bid = channel_info["twitch_channel_id"]
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

                except Exception:
                    logger.exception(
                        "[%s] Subscription health check error",
                        self.bot_name,
                    )

        except asyncio.CancelledError:
            pass

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
