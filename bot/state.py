"""Redis-backed bot state — survives deploys, unlike handler dicts.

Every merge deploys and every deploy used to wipe in-memory state:
cooldowns reset (instant replays), loaded lizard bullets evaporated,
victim callouts lost their thread. Anything a player would notice
losing lives here instead. See the state-durability principle: new
mechanics inherit old patterns, so this module is the pattern to copy.

Every helper fails open — Redis being down degrades to v1 behavior
(no cooldowns, no bullets, no victim memory) and must never break the
game itself.
"""

from __future__ import annotations

import json
import logging

import redis.asyncio as aioredis
from django.conf import settings

logger = logging.getLogger("bot")

RECENCY_WINDOW = 10  # keep in sync with lizardmood.RECENCY_WINDOW

_client: aioredis.Redis | None = None
_redis_down = False  # log-spam guard: warn on state change, not per call


def get_client() -> aioredis.Redis:
    """Lazy singleton async Redis client."""
    global _client
    if _client is None:
        _client = aioredis.from_url(
            settings.REDIS_URL, decode_responses=True
        )
    return _client


def _note_failure(op: str, exc: Exception) -> None:
    global _redis_down
    if not _redis_down:
        logger.warning("[State] Redis unavailable (%s): %s — failing open", op, exc)
        _redis_down = True


def _note_success() -> None:
    global _redis_down
    if _redis_down:
        logger.info("[State] Redis recovered")
        _redis_down = False


# --- Cooldowns ---


async def cooldown_try_acquire(key: str, seconds: int) -> bool:
    """Atomically start a cooldown. True if acquired (not on cooldown).

    A non-positive duration means no cooldown at all.
    """
    if seconds <= 0:
        return True
    try:
        acquired = await get_client().set(key, "1", ex=seconds, nx=True)
        _note_success()
        return acquired is True
    except Exception as exc:
        _note_failure("cooldown_try_acquire", exc)
        return True  # fail open: allow the play


async def cooldown_remaining(key: str) -> int:
    """Seconds left on a cooldown, 0 if none."""
    try:
        ttl = await get_client().ttl(key)
        _note_success()
        return max(ttl, 0)
    except Exception as exc:
        _note_failure("cooldown_remaining", exc)
        return 0


async def cooldown_set(key: str, seconds: int) -> None:
    """Start/refresh a cooldown unconditionally."""
    if seconds <= 0:
        return
    try:
        await get_client().set(key, "1", ex=seconds)
        _note_success()
    except Exception as exc:
        _note_failure("cooldown_set", exc)


async def cooldown_clear(key: str) -> None:
    try:
        await get_client().delete(key)
        _note_success()
    except Exception as exc:
        _note_failure("cooldown_clear", exc)


# --- Lizard bullets ---


def _bullets_key(channel_id: str) -> str:
    return f"lr:bullets:{channel_id}"


async def bullets_get(channel_id: str) -> int:
    try:
        val = await get_client().get(_bullets_key(channel_id))
        _note_success()
        return int(val) if val else 0
    except Exception as exc:
        _note_failure("bullets_get", exc)
        return 0


async def bullets_set(channel_id: str, count: int) -> None:
    try:
        await get_client().set(_bullets_key(channel_id), count)
        _note_success()
    except Exception as exc:
        _note_failure("bullets_set", exc)


async def bullets_decr(channel_id: str) -> None:
    try:
        client = get_client()
        remaining = await client.decr(_bullets_key(channel_id))
        if remaining <= 0:
            await client.delete(_bullets_key(channel_id))
        _note_success()
    except Exception as exc:
        _note_failure("bullets_decr", exc)


# --- Last victim (lizardroulette callouts) ---


# How many plays a victim stays quotable. Past this the lizard stops
# citing them: the key has no natural expiry, so without this a quiet
# week leaves it name-checking someone who died last Tuesday. Sized
# from spoonee's data — median 4 survivals between deaths, p90 12 — so
# the usual rhythm is untouched and only the stale tail is cut.
VICTIM_TTL_PLAYS = 5


def _victim_key(channel_id: str) -> str:
    return f"lr:victim:{channel_id}"


def _victim_plays_key(channel_id: str) -> str:
    return f"lr:victim_plays:{channel_id}"


async def victim_get(channel_id: str) -> str:
    try:
        val = await get_client().get(_victim_key(channel_id))
        _note_success()
        return val or ""
    except Exception as exc:
        _note_failure("victim_get", exc)
        return ""


async def victim_set(channel_id: str, name: str) -> None:
    """Record a new victim and restart their shelf life."""
    try:
        client = get_client()
        await client.set(_victim_key(channel_id), name)
        await client.set(_victim_plays_key(channel_id), 0)
        _note_success()
    except Exception as exc:
        _note_failure("victim_set", exc)


async def victim_bump(channel_id: str) -> None:
    """Count one play against the current victim's shelf life."""
    try:
        await get_client().incr(_victim_plays_key(channel_id))
        _note_success()
    except Exception as exc:
        _note_failure("victim_bump", exc)


async def victim_is_current(channel_id: str) -> bool:
    """Whether the stored victim is still recent enough to name.

    A missing counter means expired, not fresh: channels carrying a
    victim from before this counter existed, and any channel whose
    Redis was cleared, should fall back to naming nobody rather than
    claim a stale death is current.
    """
    try:
        raw = await get_client().get(_victim_plays_key(channel_id))
        _note_success()
    except Exception as exc:
        _note_failure("victim_is_current", exc)
        return False
    if raw is None:
        return False
    try:
        return int(raw) <= VICTIM_TTL_PLAYS
    except (TypeError, ValueError):
        return False


# --- Recency (message-fragment history) ---


def _recency_key(channel_id: str) -> str:
    return f"lr:recency:{channel_id}"


async def recency_get(channel_id: str) -> list[str]:
    """Most-recent-first fragment history for a channel."""
    try:
        items = await get_client().lrange(
            _recency_key(channel_id), 0, RECENCY_WINDOW - 1
        )
        _note_success()
        return items
    except Exception as exc:
        _note_failure("recency_get", exc)
        return []

async def recency_push(channel_id: str, fragments: list[str]) -> None:
    if not fragments:
        return
    try:
        client = get_client()
        await client.lpush(_recency_key(channel_id), *fragments)
        await client.ltrim(_recency_key(channel_id), 0, RECENCY_WINDOW - 1)
        _note_success()
    except Exception as exc:
        _note_failure("recency_push", exc)


# --- Pending lizard timeouts (journal for the delayed ban) ---
#
# A death's timeout fires after a theatrical delay held in an asyncio
# sleep — if a deploy kills the process inside that window, the ban
# evaporates while the death is already on the record. Journal the
# pending ban before sleeping; LizardRecovery fires survivors at the
# next startup. The lizard never forgets.

_PENDING_TIMEOUTS_KEY = "lr:pending_timeouts"


async def pending_timeout_add(
    channel_id: str,
    twitch_id: str,
    username: str,
    duration: int,
    due_at: float,
) -> None:
    """Journal a delayed timeout before its countdown starts."""
    try:
        await get_client().hset(
            _PENDING_TIMEOUTS_KEY,
            f"{channel_id}:{twitch_id}",
            json.dumps(
                {"username": username, "duration": duration, "due_at": due_at}
            ),
        )
        _note_success()
    except Exception as exc:
        _note_failure("pending_timeout_add", exc)


async def pending_timeout_clear(channel_id: str, twitch_id: str) -> None:
    """Remove a journaled timeout once the ban has been attempted."""
    try:
        await get_client().hdel(_PENDING_TIMEOUTS_KEY, f"{channel_id}:{twitch_id}")
        _note_success()
    except Exception as exc:
        _note_failure("pending_timeout_clear", exc)


async def pending_timeouts_all() -> list[dict]:
    """Every journaled timeout, with channel_id/twitch_id unpacked."""
    try:
        raw = await get_client().hgetall(_PENDING_TIMEOUTS_KEY)
        _note_success()
    except Exception as exc:
        _note_failure("pending_timeouts_all", exc)
        return []

    out = []
    for field, value in raw.items():
        try:
            entry = json.loads(value)
            channel_id, twitch_id = field.split(":", 1)
            entry["channel_id"] = channel_id
            entry["twitch_id"] = twitch_id
            out.append(entry)
        except (ValueError, KeyError):
            continue
    return out
