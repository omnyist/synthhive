"""The `bots` block in /health/ — what would have caught 2026-08-21.

That day every bot stayed connected to Twitch with a dead database behind it.
Containers read Up, this endpoint returned 200, and no command worked in any
channel for three hours while #spoonee was live. These tests pin both halves
of the fix: that the incident now speaks, and that a quiet night still doesn't.
"""

from __future__ import annotations

import time
from unittest.mock import patch

from synthhive.health import LIVE_WINDOW_S
from synthhive.health import LIVENESS_STALE_S
from synthhive.health import WORK_STALE_S
from synthhive.health import _bot_health

BOT = "elsydeon"


class FakeRedis:
    def __init__(self, values: dict[str, str] | None = None, raises: bool = False):
        self._values = values or {}
        self._raises = raises

    def scan_iter(self, match=None, count=None):
        if self._raises:
            raise ConnectionError("redis is gone")
        return iter(self._values.keys())

    def get(self, k):
        if self._raises:
            raise ConnectionError("redis is gone")
        return self._values.get(k)

    def close(self):
        pass


def _beats(bot: str = BOT, **ages: float | None) -> dict[str, str]:
    """Beats for one bot. Unnamed kinds default to fresh; None omits the key."""
    now = time.time()
    out: dict[str, str] = {}
    for kind in ("boot", "liveness", "work", "live"):
        age = ages.get(kind, 1.0)
        if age is None:
            continue
        out[f"hb:bot:{bot}:{kind}"] = str(now - age)
    return out


def _run(fake: FakeRedis) -> dict:
    status: dict = {"status": "ok", "services": {}}
    with patch("synthhive.health.redis.from_url", return_value=fake):
        _bot_health(status)
    return status


def test_a_healthy_bot_is_quiet():
    """The property that decides whether anyone keeps reading the alerts."""
    status = _run(FakeRedis(_beats()))

    assert status["services"]["bots"] == "ok"
    assert status["status"] == "ok"


def test_silence_while_a_channel_is_live_is_the_incident():
    """2026-08-21 exactly: connected to Twitch, no command completing,
    someone streaming."""
    status = _run(FakeRedis(_beats(work=WORK_STALE_S + 60, live=5)))

    assert status["status"] == "degraded"
    assert "LIVE" in status["services"]["bots"]
    assert BOT in status["services"]["bots"]


def test_the_same_silence_offline_is_not_an_incident():
    """The gate that keeps this from paging every single night.

    Identical work-staleness, no live channel — a bot nobody is talking to.
    Without this the monitor cries wolf until it is muted, and then it
    protects nothing.
    """
    status = _run(FakeRedis(_beats(work=WORK_STALE_S + 6000, live=None)))

    assert status["status"] == "ok"
    assert status["services"]["bots"] == "ok"


def test_a_stale_live_gate_closes():
    """A stream that ended hours ago must not keep the alarm armed."""
    status = _run(FakeRedis(_beats(work=WORK_STALE_S + 600, live=LIVE_WINDOW_S + 600)))

    assert status["status"] == "ok"


def test_dead_chat_plumbing_alerts_regardless_of_streaming():
    """Liveness is unconditional: the sweep runs whether or not anyone is
    live, so silence here is always actionable."""
    status = _run(FakeRedis(_beats(liveness=LIVENESS_STALE_S + 60, live=None)))

    assert status["status"] == "degraded"
    assert "chat plumbing silent" in status["services"]["bots"]


def test_booted_but_never_connected_is_named_distinctly():
    """The 2026-08-09 failure: a bot logs 'Bot is ready' with dead plumbing.
    Different fix from 'never started', so it gets different words."""
    status = _run(FakeRedis(_beats(boot=LIVENESS_STALE_S + 600, liveness=None)))

    assert status["status"] == "degraded"
    assert "never connected to Twitch" in status["services"]["bots"]


def test_one_sick_bot_among_healthy_ones_is_not_hidden():
    """runbot rebuilds a client per retry and one container runs several bots.
    A container-level key would be written by whichever bot beat last, so a
    single crash-looping bot would hide behind its healthy siblings."""
    values = {
        **_beats("elsydeon"),
        **_beats("worldfriendshipbot", liveness=LIVENESS_STALE_S + 120),
    }
    status = _run(FakeRedis(values))

    assert status["status"] == "degraded"
    assert "worldfriendshipbot" in status["services"]["bots"]
    assert "elsydeon" not in status["services"]["bots"]


def test_redis_down_is_unknown_not_every_bot_dead():
    status = _run(FakeRedis(raises=True))

    assert "unknown" in status["services"]["bots"]
    assert status["status"] == "ok"


# --- the roster, not only the beats -----------------------------------------
#
# Scanning `hb:*` can only find a bot that has beaten at least once, so a bot
# enrolled in core_bot that has never beaten at all was invisible here — the
# hole synthfunc fell into on 2026-08-31 (six workers running, /health/
# speaking for four, `workers: ok` true the whole time). The other five
# families check their roster against docker-compose in CI; synthhive's roster
# is database rows resolved at runtime, so the check lives in the endpoint and
# these tests exercise it against real rows.

import pytest  # noqa: E402

from core.models import Bot  # noqa: E402


def _enrol(username: str, name: str | None = None) -> Bot:
    return Bot.objects.create(
        name=name or username,
        twitch_user_id=f"id-{username}",
        twitch_username=username,
    )


@pytest.mark.django_db
def test_an_enrolled_bot_that_never_beat_is_reported():
    """The whole point: no beats at all means discovery cannot see it, so the
    roster has to. Absence of every beat is the strongest signal there is."""
    _enrol(BOT)                                 # healthy and beating
    _enrol("silentbot")                         # enrolled, never beat
    # Past the grace window: the process has been up long enough that silence
    # is a fault rather than a bot still starting.
    with patch("synthhive.health._SERVER_STARTED", time.time() - LIVENESS_STALE_S - 60):
        status = _run(FakeRedis(_beats()))      # beats for BOT only

    assert "silentbot: enrolled but has never beat" in status["services"]["bots"]
    assert status["status"] == "degraded"


@pytest.mark.django_db
def test_a_never_beaten_bot_is_not_a_fault_while_the_process_is_young():
    """Right after a deploy this is a bot that has not come up yet. A monitor
    that cannot stay quiet through a restart is one that gets muted."""
    _enrol(BOT)
    _enrol("silentbot")
    with patch("synthhive.health._SERVER_STARTED", time.time()):
        status = _run(FakeRedis(_beats()))

    assert status["services"]["bots"] == "ok"
    assert status["status"] == "ok"


@pytest.mark.django_db
def test_a_beating_bot_that_left_the_roster_is_reported():
    """The other direction. Retiring a bot means deleting its beats; until
    that happens this says so rather than counting it as healthy — questlog's
    shed Celery, in synthhive's clothing."""
    status = _run(FakeRedis(_beats(bot="ghostbot")))   # beats, but no core_bot row

    assert "ghostbot: beating but not enrolled in core_bot" in status["services"]["bots"]
    assert status["status"] == "degraded"


@pytest.mark.django_db
def test_an_enrolled_and_beating_bot_stays_quiet():
    """Both halves agreeing must remain silent, or the check is noise."""
    _enrol(BOT)
    status = _run(FakeRedis(_beats()))

    assert status["services"]["bots"] == "ok"
    assert status["status"] == "ok"
