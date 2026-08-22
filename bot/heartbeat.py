"""Bot heartbeats: proof the bot is doing its job, not that its process exists.

On 2026-08-21 a shared-Postgres restart left every bot connected to Twitch
with dead database plumbing. `docker ps` said Up, the panel returned 200,
`bots.bardsaders.com` was green, and not one command worked in any channel for
three hours — while #spoonee was live with 65 people in chat. Nothing in the
rack could tell the difference between that and a quiet night.

Three beats, because the bot has three failure modes that look identical from
outside:

    boot      written once at process start, before any Twitch connection.
              Absent means the process never came up at all.
    liveness  written from the 60s subscription health check, which walks the
              live WebSockets. Proves the chat plumbing, not just the event
              loop — TwitchIO dispatches no keepalive event, so this sweep is
              the only recurring proof the socket is real.
    work      written after a command is fully handled: cooldown recorded,
              use_count saved to Postgres, reply sent to Twitch. Proves the
              whole path, which is exactly the path that was broken.

**The work beat alone is useless and dangerous.** Commands only arrive when
someone types one, so an offline channel produces none for many hours — a
staleness alarm on it would page nightly about perfectly healthy bots, and the
rack's own rule is that idle is not broken. So a `live` beat records when a
channel was last observed streaming, and the monitor only treats work-staleness
as actionable while that is fresh. Silence during a live stream is the
incident; silence at 4am is Tuesday.

**Keyed per bot, never per process.** `runbot` rebuilds a whole BotClient on
every retry with 5s→300s backoff, and one container runs several bots at once.
A container-level key would be written by whichever bot beat last, so a single
bot crash-looping behind two healthy ones would look continuous — and that
crash loop is the 2026-08-09 failure where a bot logged "Bot is ready" with
dead chat plumbing.

Every write fails open, following this project's existing state.py contract:
Redis being down degrades the game to v1 behaviour and must never break it.
A monitoring write that can kill a chat response has inverted the relationship
between the monitor and the monitored.
"""

from __future__ import annotations

import logging
import time

from .state import _note_failure
from .state import _note_success
from .state import get_client

logger = logging.getLogger("bot")

KEY_PREFIX = "hb:bot"

# Long enough to outlive any threshold, short enough that a retired bot's keys
# disappear on their own rather than lingering as phantom evidence.
TTL_SECONDS = 24 * 60 * 60


def key(bot_name: str, kind: str) -> str:
    return f"{KEY_PREFIX}:{bot_name.lower()}:{kind}"


async def _beat(bot_name: str, kind: str) -> None:
    try:
        await get_client().set(key(bot_name, kind), str(time.time()), ex=TTL_SECONDS)
        _note_success()
    except Exception as exc:  # noqa: BLE001 — see module docstring
        _note_failure(f"heartbeat {kind}", exc)


async def beat_liveness(bot_name: str) -> None:
    """The chat plumbing is alive. Call from the subscription health sweep."""
    await _beat(bot_name, "liveness")


async def beat_work(bot_name: str) -> None:
    """A command was handled end to end — DB write and Twitch reply included."""
    await _beat(bot_name, "work")


async def beat_live(bot_name: str) -> None:
    """A channel this bot serves was just observed live.

    Written from the component ticks that already ask Twitch this question, so
    it costs no extra API calls. If no component runs for a channel the beat
    simply never appears, and work-staleness stays unalertable for that bot —
    the safe direction to fail, since a missing gate should silence an alarm
    rather than invent one.
    """
    await _beat(bot_name, "live")


def beat_boot_sync(bot_name: str) -> None:
    """Process start, before any Twitch connection is attempted.

    Sync because it runs from `runbot`'s handle() before the event loop, and
    it exists so 'never started' reads differently from 'started but never
    connected' — two failures with different fixes that otherwise produce
    identical silence.
    """
    try:
        import redis
        from django.conf import settings

        client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            client.set(key(bot_name, "boot"), str(time.time()), ex=TTL_SECONDS)
        finally:
            client.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("[Heartbeat] Could not record boot for %s: %s", bot_name, exc)
