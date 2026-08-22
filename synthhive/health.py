from __future__ import annotations

import time

import redis
from django.conf import settings
from django.db import connection
from django.http import HttpRequest
from django.http import JsonResponse

from bot.heartbeat import KEY_PREFIX

# The chat plumbing must prove itself every minute. The subscription sweep runs
# on a 60s loop, so three missed sweeps is a real stall rather than jitter.
LIVENESS_STALE_S = 240

# Commands only arrive when someone types one, so this is deliberately
# generous: it is not "how often should commands happen" but "how long a live
# channel can plausibly go without a single one before something is wrong".
WORK_STALE_S = 900

# How long after the last observed live tick we keep treating work-silence as
# suspicious. Comfortably past accrual's 5-minute cadence so the gate does not
# flap shut between ticks of a stream that is still running.
LIVE_WINDOW_S = 900

# A bot that has never beat is only benign while its process is young.
_SERVER_STARTED = time.time()


def _bot_health(status: dict) -> None:
    """Report each bot's beats — the signal that would have caught 2026-08-21.

    That day every bot held a dead database connection for three hours. They
    stayed connected to Twitch, the container read Up, this endpoint returned
    200, and not one command worked while #spoonee was live with 65 people
    watching. `liveness` was the thing that stayed true and `work` was the
    thing that stopped, which is precisely why they are separate beats.

    Redis unreachable renders as `unknown`: a Redis outage and every bot dying
    are different incidents, and one must never be dressed as the other.
    """
    try:
        client = redis.from_url(
            settings.REDIS_URL, socket_connect_timeout=2, decode_responses=True
        )
    except Exception:
        status["services"]["bots"] = "unknown (redis unreachable)"
        return

    try:
        now = time.time()
        names = set()
        for k in client.scan_iter(match=f"{KEY_PREFIX}:*", count=200):
            parts = k.split(":")
            if len(parts) >= 4:
                names.add(parts[2])

        if not names:
            # No bot has ever beat. Benign right after a deploy, and a real
            # signal once the process has had time to come up.
            if now - _SERVER_STARTED > LIVENESS_STALE_S:
                status["services"]["bots"] = "no bot has ever beat"
                status["status"] = "degraded"
            else:
                status["services"]["bots"] = "starting"
            return

        problems: list[str] = []
        detail: dict[str, dict] = {}

        for name in sorted(names):
            ages: dict[str, float | None] = {}
            for kind in ("boot", "liveness", "work", "live"):
                raw = client.get(f"{KEY_PREFIX}:{name}:{kind}")
                ages[kind] = round(now - float(raw), 1) if raw else None
            detail[name] = ages

            boot = ages["boot"]
            running_for = boot if boot is not None else now - _SERVER_STARTED

            # Liveness is unconditional: the sweep runs whether or not anyone
            # is streaming, so silence here is always actionable.
            live_age = ages["liveness"]
            if live_age is None:
                if running_for > LIVENESS_STALE_S:
                    how = (
                        "never connected to Twitch"
                        if boot is not None
                        else "process never started"
                    )
                    problems.append(f"{name}: {how}")
            elif live_age > LIVENESS_STALE_S:
                problems.append(f"{name}: chat plumbing silent {live_age:.0f}s")

            # Work staleness only counts while a channel is actually live.
            # Without this gate every bot would page overnight, and the rack's
            # own rule is that idle is not broken.
            streaming = ages["live"] is not None and ages["live"] < LIVE_WINDOW_S
            work_age = ages["work"]
            if streaming and (work_age is None or work_age > WORK_STALE_S):
                seen = "never" if work_age is None else f"{work_age:.0f}s ago"
                problems.append(
                    f"{name}: no command handled since {seen} while a channel is LIVE"
                )

        status["services"]["bots"] = "; ".join(problems) if problems else "ok"
        status["bot_beats"] = detail
        if problems:
            status["status"] = "degraded"
    except Exception as exc:  # noqa: BLE001
        status["services"]["bots"] = f"unknown ({exc})"
    finally:
        try:
            client.close()
        except Exception:
            pass


def health_check(request: HttpRequest) -> JsonResponse:
    """Health of this project — the API process AND the bots behind it.

    This used to speak only for the Daphne process answering it, which is how
    a three-hour, all-channels command outage sat behind a 200.
    """
    status: dict = {"status": "ok", "services": {}}
    http_status = 200

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        status["services"]["database"] = "ok"
    except Exception as e:
        status["services"]["database"] = f"error: {str(e)}"
        status["status"] = "degraded"
        http_status = 503

    try:
        r = redis.from_url(settings.REDIS_URL, socket_connect_timeout=2)
        r.ping()
        status["services"]["redis"] = "ok"
    except Exception as e:
        status["services"]["redis"] = f"error: {str(e)}"
        status["status"] = "degraded"
        http_status = 503

    _bot_health(status)
    if status["status"] == "degraded":
        http_status = 503

    return JsonResponse(status, status=http_status)
