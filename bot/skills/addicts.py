"""!addicts — Show the most frequent lizardroulette players."""

from __future__ import annotations

import logging
from datetime import UTC
from datetime import datetime

from bot.router import send_reply
from bot.skills import SkillHandler
from bot.skills import register_skill
from core.synthfunc import _get

logger = logging.getLogger("bot")

TOP_N = 5


def _format_interval(seconds: float) -> str:
    """Format seconds into a human-readable interval."""
    minutes = int(seconds / 60)
    if minutes < 60:
        return f"{minutes}m"
    hours = minutes // 60
    remaining = minutes % 60
    if remaining:
        return f"{hours}h {remaining}m"
    return f"{hours}h"


def _compute_avg_interval(timestamps: list[str]) -> float | None:
    """Compute average interval in seconds from ISO timestamp strings."""
    if len(timestamps) < 2:
        return None
    times = sorted(
        datetime.fromisoformat(ts).replace(tzinfo=UTC)
        if ts.endswith("Z") is False
        else datetime.fromisoformat(ts.replace("Z", "+00:00"))
        for ts in timestamps
    )
    total = (times[-1] - times[0]).total_seconds()
    return total / (len(times) - 1)


class AddictsHandler(SkillHandler):
    """!addicts — Show the lizard's most frequent visitors."""

    name = "addicts"

    async def handle(self, payload, args, skill, bot):
        chatter = payload.chatter
        if not chatter:
            return

        broadcaster_id = str(payload.broadcaster.id)

        from core.models import Channel

        try:
            from asgiref.sync import sync_to_async

            channel = await sync_to_async(Channel.objects.get)(
                twitch_channel_id=broadcaster_id,
                is_active=True,
            )
        except Channel.DoesNotExist:
            return

        slug = channel.twitch_channel_name
        data = await _get(
            "/events/lizardroulette-usage",
            tenant_slug=slug,
        )

        if not data or not data.get("users"):
            await send_reply(
                payload,
                "The lizard has no regulars... yet. bardLizard",
                bot_id=bot.bot_id,
            )
            return

        entries = []
        for user in data["users"]:
            count = len(user["timestamps"])
            avg = _compute_avg_interval(user["timestamps"])
            entries.append((user["display_name"], count, avg))

        entries.sort(key=lambda x: x[1], reverse=True)
        entries = entries[:TOP_N]

        parts = []
        for i, (name, count, avg) in enumerate(entries, 1):
            if avg is not None:
                parts.append(f"{i}. {name} ({count}, every {_format_interval(avg)})")
            else:
                parts.append(f"{i}. {name} ({count})")

        leaderboard = ", ".join(parts)
        message = f"The lizard's most loyal customers... {leaderboard} bardLizard"
        await send_reply(payload, message, bot_id=bot.bot_id)


register_skill(AddictsHandler())
