from __future__ import annotations

import asyncio
import contextlib
import logging
from unittest.mock import AsyncMock
from unittest.mock import MagicMock
from unittest.mock import patch

import pytest

from bot.components.base import TickingComponent


class _Recorder(TickingComponent):
    """A minimal TickingComponent that records call order for one tick."""

    TICK_INTERVAL = 999  # never fires again within a test
    STARTUP_DELAY = 0

    def __init__(self, bot) -> None:
        super().__init__(bot)
        self.calls: list[str] = []

    async def _tick_channel(self, channel_info: dict) -> None:
        self.calls.append(f"tick:{channel_info['name']}")


def _make_bot():
    bot = MagicMock()
    bot._channel_map = {"spoonee": {"name": "spoonee", "twitch_channel_id": "1"}}
    return bot


async def _run_one_tick(component: TickingComponent) -> None:
    """Start the real _tick_loop, let one tick happen, then cancel it."""
    task = asyncio.create_task(component._tick_loop())
    await asyncio.sleep(0.05)
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


@pytest.mark.asyncio
async def test_tick_loop_releases_connection_before_ticking_any_channel():
    """The one guarantee this class exists to make structural rather than
    remembered: aclose_old_connections() runs before _tick_channel, every
    tick, for every subclass -- see bot/components/base.py.
    """
    component = _Recorder(_make_bot())

    with patch("bot.components.base.aclose_old_connections", new=AsyncMock()) as released:
        released.side_effect = lambda: component.calls.append("release")
        await _run_one_tick(component)

    assert component.calls == ["release", "tick:spoonee"]


def test_a_subclass_missing_tick_interval_cannot_even_be_constructed():
    """TICK_INTERVAL is a bare annotation with no default. Before this check,
    a subclass that forgot to set it would construct fine and only fail 300s
    later inside _tick_loop, as an AttributeError outside every except clause
    in the loop -- the task dies with nothing logged. Failing at __init__
    means it fails at bot startup instead, loudly, in the one place a human
    is actually watching. Adversarial review, 2026-09-08 pass 2.
    """

    class Incomplete(TickingComponent):
        STARTUP_DELAY = 0

    with pytest.raises(TypeError, match="TICK_INTERVAL"):
        Incomplete(_make_bot())


@pytest.mark.asyncio
async def test_subclass_missing_tick_channel_logs_loudly_every_tick_in_the_real_loop(
    caplog,
):
    """Proves the claim against the actual _tick_loop, not just the method in
    isolation: a forgotten _tick_channel override doesn't crash the task, but
    it does log an exception on every single tick, forever -- loud, not
    silent. Adversarial review, 2026-09-08 pass 2, correctly pointed out the
    original version of this test only called _tick_channel directly and
    never proved anything about the loop's real behavior.
    """

    class Incomplete(TickingComponent):
        TICK_INTERVAL = 999
        STARTUP_DELAY = 0

    component = Incomplete(_make_bot())

    with patch("bot.components.base.aclose_old_connections", new=AsyncMock()):
        with caplog.at_level(logging.ERROR, logger="bot"):
            await _run_one_tick(component)

    assert "NotImplementedError" in caplog.text
    assert "Error processing #spoonee" in caplog.text


@pytest.mark.asyncio
async def test_a_failing_aclose_old_connections_does_not_kill_the_tick_loop():
    """aclose_old_connections() sits outside the per-channel try/except, so a
    naive reading suggests a transient DB error there would escape _tick_loop
    entirely and kill the task permanently -- the same failure shape as the
    missing-TICK_INTERVAL bug, just at a different line. It's wrapped in its
    own try now (matching questlog's run_worker_loop, which already treated a
    whole-tick failure this way); this proves the loop survives and keeps
    ticking on the next interval instead of dying silently.
    """
    component = _Recorder(_make_bot())
    attempts = 0

    async def flaky_release():
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("connection is closed")
        component.calls.append("release")

    with patch("bot.components.base.aclose_old_connections", side_effect=flaky_release):
        task = asyncio.create_task(component._tick_loop())
        # TICK_INTERVAL=999 means only a live, un-killed loop could reach a
        # second iteration this fast -- there is no sleep long enough to
        # fake this by accident.
        component.TICK_INTERVAL = 0.02
        await asyncio.sleep(0.08)
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task

    assert attempts >= 2
    assert "tick:spoonee" in component.calls
