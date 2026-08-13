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

    async def handle(self, payload, args, skill, bot, channel):
        chatter = payload.chatter
        if not chatter:
            return

        from core.models import SkillStat

        survivors = await sync_to_async(list)(
            SkillStat.objects.filter(
                channel=channel,
                skill_name="lizardroulette",
                max_streak__gt=0,
            )
            .order_by("-max_streak")
            .values_list("twitch_username", "max_streak")[:TOP_N]
        )

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
