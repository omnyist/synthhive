from __future__ import annotations

import logging

from asgiref.sync import sync_to_async

from bot.router import send_reply
from bot.skills import SkillHandler
from bot.skills import register_skill

logger = logging.getLogger("bot")

TOP_N = 5


class SurvivorsHandler(SkillHandler):
    """!survivors — Show the lizard's luckiest survivors."""

    name = "survivors"

    async def handle(self, payload, args, skill, bot):
        chatter = payload.chatter
        if not chatter:
            return

        broadcaster_id = str(payload.broadcaster.id)

        from core.models import Channel
        from core.models import SkillStat

        try:
            channel = await sync_to_async(Channel.objects.get)(
                twitch_channel_id=broadcaster_id,
                is_active=True,
            )
        except Channel.DoesNotExist:
            return

        stats = await sync_to_async(list)(
            SkillStat.objects.filter(
                channel=channel,
                skill_name="lizardroulette",
            )
        )

        survivors = [
            (s.twitch_username, s.stats.get("max_streak", 0))
            for s in stats
            if s.stats.get("max_streak", 0) > 0
        ]
        survivors.sort(key=lambda x: x[1], reverse=True)
        survivors = survivors[:TOP_N]

        if not survivors:
            await send_reply(
                payload,
                "No one has survived the lizard... yet. bardLizard",
                bot_id=bot.bot_id,
            )
            return

        leaderboard = ", ".join(
            f"{i}. {name} ({streak})"
            for i, (name, streak) in enumerate(survivors, 1)
        )
        message = f"The lizard's luckiest survivors... {leaderboard} bardLizard"
        await send_reply(payload, message, bot_id=bot.bot_id)


register_skill(SurvivorsHandler())
