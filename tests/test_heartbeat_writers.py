"""The bot-side beat writers — the half tests/test_bot_health.py doesn't cover.

test_bot_health.py pins how /health/ *reads* beats. These pin how the bot
*writes* them, which is where a monitoring bug fails silently: a beat writer
that raises would take a chat handler down with it, and one that quietly
writes the wrong thing turns the whole endpoint into decoration.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from bot.heartbeat import TTL_SECONDS
from bot.heartbeat import key
from bot.heartbeat import refresh_boot_ttl

BOT = "elsydeon"


@pytest.mark.asyncio
async def test_refresh_boot_ttl_extends_without_touching_the_value(monkeypatch):
    """EXPIRE only. The timestamp must stay the true process start.

    If this ever became a SET, every liveness sweep would rewrite boot to
    "now" — and a bot that has been crash-looping for hours would report a
    boot age of 60 seconds, which is the opposite of what the key is for.
    """
    client = AsyncMock()
    monkeypatch.setattr("bot.heartbeat.get_client", lambda: client)

    await refresh_boot_ttl(BOT)

    client.expire.assert_awaited_once_with(key(BOT, "boot"), TTL_SECONDS)
    client.set.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_boot_ttl_fails_open(monkeypatch):
    """Redis being gone must never propagate into the caller.

    This runs inside the subscription health sweep, so an exception here
    would break the loop that keeps bots subscribed — monitoring taking down
    the thing it monitors.
    """
    client = AsyncMock()
    client.expire.side_effect = ConnectionError("redis is gone")
    monkeypatch.setattr("bot.heartbeat.get_client", lambda: client)

    await refresh_boot_ttl(BOT)  # must not raise


@pytest.mark.asyncio
async def test_boot_key_is_per_bot(monkeypatch):
    """Keyed per bot name, not per process.

    runbot rebuilds a whole BotClient per retry, so a per-process key would
    make a crash-looping bot look continuous.
    """
    assert key("elsydeon", "boot") != key("tifathesoldier", "boot")
    assert key("Elsydeon", "boot") == key("elsydeon", "boot")


def test_ttl_outlives_the_liveness_sweep_that_refreshes_it():
    """The refresh cadence must be far below the TTL it refreshes.

    The sweep runs every 60s; if TTL ever dropped near that, a single slow
    sweep would let boot expire and the never-beat message would regress to
    "process never started" for a healthy bot.
    """
    SWEEP_INTERVAL_S = 60
    assert TTL_SECONDS > SWEEP_INTERVAL_S * 100
