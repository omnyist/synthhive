"""bot/heartbeat.py's naming policy — the one thing synthlib's own tests
can't know.

The beat writers themselves (fail-open, boot-TTL refresh, key shape) are
synthlib.django.heartbeat's contracts now, proven once in synthlib's own
test suite. What's left here is synthhive-specific: `worker_id` lowercases
a bot name and prefixes "bot:" so the resulting `hb:bot:<name>:<kind>` key
keeps matching what /health/'s `_bot_health` scans and parses.
"""

from __future__ import annotations

from bot.heartbeat import worker_id


def test_worker_id_is_keyed_per_bot_not_per_process():
    """runbot rebuilds a whole BotClient per retry, so a per-process id would
    make a crash-looping bot look continuous."""
    assert worker_id("elsydeon") != worker_id("tifathesoldier")


def test_worker_id_is_case_insensitive():
    assert worker_id("Elsydeon") == worker_id("elsydeon")


def test_worker_id_is_prefixed_for_the_health_endpoints_scan():
    """/health/'s _bot_health scans `hb:bot:*` and reads the bot name from
    the third ':'-separated segment -- this prefix is what keeps that
    parsing working unchanged after the migration to synthlib."""
    assert worker_id("elsydeon") == "bot:elsydeon"
