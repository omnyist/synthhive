from __future__ import annotations

import logging

from asgiref.sync import sync_to_async

from bot.router import send_reply
from bot.skills import SkillHandler
from bot.skills import register_skill

logger = logging.getLogger("bot")

TOP_N = 5


class VictimsHandler(SkillHandler):
    """!victims — Show the lizard's most frequent targets."""

    name = "victims"

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

        victims = await sync_to_async(list)(
            SkillStat.objects.filter(
                channel=channel,
                skill_name="lizardroulette",
                deaths__gt=0,
            )
            .order_by("-deaths")
            .values_list("twitch_username", "deaths")[:TOP_N]
        )

        if not victims:
            await send_reply(
                payload,
                "The lizard has no victims... yet. bardLizard",
                bot_id=bot.bot_id,
            )
            return

        leaderboard = ", ".join(
            f"{i}. {name} ({deaths})"
            for i, (name, deaths) in enumerate(victims, 1)
        )
        message = f"The lizard has broken its back digging graves for... {leaderboard} bardLizard"
        await send_reply(payload, message, bot_id=bot.bot_id)


register_skill(VictimsHandler())
