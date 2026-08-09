from __future__ import annotations

import asyncio
import logging
import time

from asgiref.sync import sync_to_async
from django.conf import settings
from django.core.management.base import BaseCommand

logger = logging.getLogger("bot")


def _load_bot_configs():
    """Load bot configurations from the database (sync context)."""
    from core.models import Bot as BotModel

    bots_qs = BotModel.objects.filter(
        channels__is_active=True,
    ).distinct()

    configs = []

    for bot_record in bots_qs:
        if not bot_record.access_token:
            logger.warning(
                "Skipping %s — no access token. Run the setup flow first.",
                bot_record.name,
            )
            continue

        channels = []
        for ch in bot_record.channels.filter(is_active=True):
            channels.append(
                {
                    "name": ch.twitch_channel_name,
                    "twitch_channel_id": ch.twitch_channel_id,
                }
            )

        if not channels:
            logger.warning("Skipping %s — no active channels.", bot_record.name)
            continue

        configs.append(
            {
                "bot_id": bot_record.twitch_user_id,
                "bot_name": bot_record.name,
                "token": bot_record.access_token,
                "refresh_token": bot_record.refresh_token,
                "channels": channels,
            }
        )

    return configs


class Command(BaseCommand):
    help = "Run TwitchIO bot instances for all active bots."

    def handle(self, *args, **options):
        self.stdout.write(self.style.SUCCESS("Starting Synthhive..."))

        try:
            asyncio.run(self._run())
        except KeyboardInterrupt:
            self.stdout.write(self.style.WARNING("\nShutting down..."))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error: {e}"))
            logger.error("Bot error: %s", e, exc_info=True)
            raise

    async def _run(self):
        configs = await sync_to_async(_load_bot_configs)()

        base_port = 4343
        for cfg in configs:
            logger.info(
                "Loaded %s (channels: %s)",
                cfg["bot_name"],
                ", ".join(f"#{ch['name']}" for ch in cfg["channels"]),
            )

        if not configs:
            logger.error(
                "No bots to run. Create a Bot in the admin and complete the setup flow."
            )
            return

        self.stdout.write(
            self.style.SUCCESS(f"Starting {len(configs)} bot(s)...")
        )

        tasks = [
            asyncio.create_task(self._run_bot(cfg, base_port + i))
            for i, cfg in enumerate(configs)
        ]

        try:
            await asyncio.gather(*tasks)
        except Exception:
            logger.exception("Bot task failed.")
            for task in tasks:
                task.cancel()
            raise

    def _build_client(self, cfg: dict, port: int):
        from bot.client import BotClient

        return BotClient(
            client_id=settings.TWITCH_CLIENT_ID,
            client_secret=settings.TWITCH_CLIENT_SECRET,
            bot_id=cfg["bot_id"],
            bot_name=cfg["bot_name"],
            token=cfg["token"],
            refresh_token=cfg["refresh_token"],
            channels=cfg["channels"],
            port=port,
        )

    async def _run_bot(self, cfg: dict, port: int):
        """Run a single bot, rebuilding the client for every attempt.

        A TwitchIO client whose start() failed is not safely
        restartable: after the 2026-08-09 power outage, retrying
        start() on the same instance reported "Bot is ready" with none
        of its chat plumbing working — 30 minutes of dead commands
        until a manual container restart. A fresh instance per attempt
        makes the retry loop actually mean something.
        """
        backoff = 5
        max_backoff = 300

        while True:
            client = self._build_client(cfg, port)
            attempt_started = time.monotonic()
            try:
                await client.start()
                break
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception(
                    "[%s] Bot crashed, restarting in %ds...",
                    cfg["bot_name"],
                    backoff,
                )
                try:
                    await client.close()
                except Exception:
                    logger.debug(
                        "[%s] Close after failed start also failed",
                        cfg["bot_name"],
                    )
                # A crash after a healthy stretch is a new incident,
                # not the same failure repeating — restart the backoff.
                if time.monotonic() - attempt_started > 300:
                    backoff = 5
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, max_backoff)
