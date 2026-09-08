"""Synthhive's Redis worker-id convention for synthlib's heartbeat primitives.

Bots are keyed by name, not by process — runbot rebuilds a whole BotClient on
every retry with 5s-300s backoff, and one container runs several bots at
once, so a per-process key would let a crash-looping bot hide behind healthy
siblings. `worker_id` lowercases (so "Elsydeon" and "elsydeon" beat the same
key) and prefixes "bot:" so the resulting key — `hb:bot:<name>:<kind>` via
synthlib's `hb:<worker>:<kind>` shape — matches what `/health/`'s `_bot_health`
already scans and parses (`parts[2]` as the bot name). The beats themselves
are synthlib.django.heartbeat's; this file is now just the naming policy.
"""

from __future__ import annotations

KEY_PREFIX = "hb:bot"


def worker_id(bot_name: str) -> str:
    return f"bot:{bot_name.lower()}"
