"""!cute — Compliment someone. Or try complimenting the bot.

Usage:
    !cute          — You're cute
    !cute @kefka   — kefka is cute
    !cute elsydeon — avalonREVERSE
"""

from __future__ import annotations

import logging

from pydantic import BaseModel
from pydantic import ConfigDict

from bot.router import send_reply
from bot.skills import SkillHandler
from bot.skills import register_skill

logger = logging.getLogger("bot")


class CuteConfig(BaseModel):
    """Config schema — validated at every write path.

    Tenant-neutral defaults: the bot-name easter egg only fires when a
    channel configures `bot_name` (existing rows were frozen by
    migration 0016).
    """

    model_config = ConfigDict(extra="forbid")

    bot_name: str = ""
    bot_response: str = "Oh, stop it, you."
    response: str = "$(target) is cute, pass it on."


class CuteHandler(SkillHandler):
    """!cute — Compliment someone, pass it on."""

    name = "cute"
    config_schema = CuteConfig

    async def handle(self, payload, args, skill, bot, channel):
        chatter = payload.chatter
        if not chatter:
            return

        config = skill.config or {}
        bot_name = config.get("bot_name", "")
        bot_response = config.get("bot_response", "Oh, stop it, you.")
        template = config.get("response", "$(target) is cute, pass it on.")

        if args:
            target = args.strip().lstrip("@")
        else:
            target = chatter.display_name

        if target.lower() == bot_name.lower():
            await send_reply(payload, bot_response, bot_id=bot.bot_id)
            return

        message = template.replace("$(target)", target)
        await send_reply(payload, message, bot_id=bot.bot_id)


register_skill(CuteHandler())
