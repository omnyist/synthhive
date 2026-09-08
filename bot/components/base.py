"""Shared base for background Components that tick on a fixed interval.

Before this existed, CurrencyAccrual, LizardBullets and TimedMessages each
carried a byte-for-byte identical `_tick_loop`: sleep a startup delay, loop
forever over `self.bot._channel_map`, isolate each channel's exception,
sleep `TICK_INTERVAL`. That duplication is precisely why the 2026-09-07
connection-release fix had to be typed out three separate times by hand
(adversarial review, 2026-09-08) -- three chances for one of them to be
skipped, mistyped, or simply not copied when a fourth ticking component gets
added later. This class ends that: `_tick_channel` and `TICK_INTERVAL` are
the only things a subclass supplies, so the release, the loop, the per-
channel isolation and the task lifecycle are a property of inheriting from
this class rather than of an author's memory.
"""

from __future__ import annotations

import asyncio
import logging

from twitchio.ext import commands

from core.db import release_connection

logger = logging.getLogger("bot")


class TickingComponent(commands.Component):
    """A Component whose background task ticks over every channel on an interval.

    Subclasses set `TICK_INTERVAL` (seconds) and implement `_tick_channel`.
    `STARTUP_DELAY` defaults to 10s -- override it if a component needs
    longer for the bot to finish connecting first (TimedMessages used 20s).
    """

    TICK_INTERVAL: float
    STARTUP_DELAY: float = 10
    # Preserves each component's pre-refactor log prefix exactly (adversarial
    # review, 2026-09-08 pass 2) -- type(self).__name__ would silently rename
    # CurrencyAccrual's "[Accrual]" to "[CurrencyAccrual]" in every log line,
    # breaking any saved search or alert keyed on the old string. Override in
    # a subclass only if a truly new component needs it; the default matches
    # the class name for anything not migrated from a hand-rolled loop.
    LOG_NAME: str | None = None

    def __init__(self, bot: commands.Bot) -> None:
        # Fails at construction (bot startup), not 300s into the first tick:
        # a subclass access TICK_INTERVAL is a bare annotation with no
        # default, and an AttributeError raised from inside _tick_loop
        # escapes its only except clause (CancelledError) uncaught, killing
        # the task permanently with nothing logged. Adversarial review,
        # 2026-09-08 pass 2 -- the exact silent-failure shape this class
        # exists to prevent, reintroduced by the class itself.
        if not hasattr(type(self), "TICK_INTERVAL"):
            raise TypeError(f"{type(self).__name__} must set TICK_INTERVAL")
        self.bot = bot
        self._task: asyncio.Task | None = None

    async def component_load(self) -> None:
        self._task = asyncio.create_task(self._tick_loop())

    async def component_teardown(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()

    async def _tick_loop(self) -> None:
        name = self.LOG_NAME or type(self).__name__
        try:
            await asyncio.sleep(self.STARTUP_DELAY)
            while True:
                try:
                    # Once per tick, before any channel's ORM call -- see
                    # core/db.py for why every independent loop needs its
                    # own call rather than relying on some other loop's.
                    # This is the one line the whole class exists to
                    # guarantee, and it is inside this try -- a transient
                    # DB error here must not kill the tick loop permanently
                    # any more than a bad channel does (questlog's
                    # run_worker_loop already treats a whole-tick failure
                    # this way; adversarial review, 2026-09-08 pass 2,
                    # caught the asymmetry).
                    await release_connection()
                    for channel_info in self.bot._channel_map.values():
                        try:
                            await self._tick_channel(channel_info)
                        except Exception:
                            logger.exception(
                                "[%s] Error processing #%s",
                                name,
                                channel_info["name"],
                            )
                except Exception:
                    logger.exception("[%s] Tick failed", name)
                await asyncio.sleep(self.TICK_INTERVAL)
        except asyncio.CancelledError:
            logger.info("[%s] Tick loop cancelled.", name)

    async def _tick_channel(self, channel_info: dict) -> None:
        """Run one tick for a single channel. Subclasses must override this."""
        raise NotImplementedError
