from __future__ import annotations

import random

from bot.skills import SkillHandler
from bot.skills import register_skill


class FlaskHandler(SkillHandler):
    """Get Ye Flask — a random chance game.

    Skill config:
        odds (int): Percent chance of success (1-100). Default: 5.
        success (str): Message on success. Supports {user}.
        failure (str): Message on failure. Supports {user}.
    """

    name = "getyeflask"

    async def handle(self, payload, args, skill):
        odds = skill.config.get("odds", 5)
        chatter = payload.chatter.name if payload.chatter else "someone"

        if random.randint(1, 100) <= odds:
            msg = skill.config.get("success", "{user} got ye flask! 🎉")
        else:
            msg = skill.config.get("failure", "You can't get ye flask!")

        await payload.respond(msg.format(user=chatter))


register_skill(FlaskHandler())
