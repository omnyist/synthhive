from __future__ import annotations

import asyncio
import logging
import random
import time

from asgiref.sync import sync_to_async

from bot.router import send_reply
from bot.skills import SkillHandler
from bot.skills import register_skill
from core.twitch import TWITCH_API_BASE
from core.twitch import twitch_request

logger = logging.getLogger("bot")


class LizardRouletteHandler(SkillHandler):
    """!lizardroulette — Roll the dice. Lose and get timed out."""

    name = "lizardroulette"

    def __init__(self):
        self._cooldowns: dict[str, float] = {}

    async def handle(self, payload, args, skill, bot):
        chatter = payload.chatter
        if not chatter:
            return

        chatter_id = str(chatter.id)
        chatter_name = chatter.display_name
        config = skill.config or {}

        # --- Per-user cooldown ---
        cooldown = config.get("cooldown", 300)
        now = time.monotonic()
        last_used = self._cooldowns.get(chatter_id)
        if last_used and (now - last_used) < cooldown:
            cooldown_response = config.get("cooldown_response")
            if cooldown_response:
                remaining = int(cooldown - (now - last_used))
                message = cooldown_response.replace(
                    "$(user)", chatter_name
                ).replace("$(remaining)", str(remaining))
                await send_reply(payload, message, bot_id=bot.bot_id)
            return

        self._cooldowns[chatter_id] = now

        # --- Roll ---
        odds = config.get("odds", 16)
        if random.randint(1, 100) <= odds:
            # Loss
            failure = config.get(
                "failure",
                "You lose $(user). Reach for the sky. 3, 2, 1... LizardWithAGun",
            )
            message = failure.replace("$(user)", chatter_name)
            await send_reply(payload, message, bot_id=bot.bot_id)

            timeout_delay = config.get("timeout_delay", 3)
            timeout_duration = config.get("timeout_duration", 600)
            await asyncio.sleep(timeout_delay)
            timed_out = await self._timeout_user(
                payload, chatter_id, timeout_duration, bot
            )

            if not timed_out:
                timeout_failed = config.get("timeout_failed")
                if timeout_failed:
                    msg = timeout_failed.replace("$(user)", chatter_name)
                    await send_reply(payload, msg, bot_id=bot.bot_id)
        else:
            # Win
            success = config.get(
                "success",
                "*click* You survived $(user). Congrats, have some serotonin. bardLizard",
            )
            message = success.replace("$(user)", chatter_name)
            await send_reply(payload, message, bot_id=bot.bot_id)

    async def _timeout_user(
        self,
        payload,
        user_id: str,
        duration: int,
        bot,
    ) -> bool:
        """Issue a timeout via the Twitch Helix moderation API.

        Returns True if the timeout succeeded, False otherwise.
        """
        broadcaster_id = str(payload.broadcaster.id)

        from core.models import Channel

        try:
            channel = await sync_to_async(Channel.objects.get)(
                twitch_channel_id=broadcaster_id,
                is_active=True,
            )
        except Channel.DoesNotExist:
            logger.warning(
                "No active channel found for broadcaster %s", broadcaster_id
            )
            return False

        url = (
            f"{TWITCH_API_BASE}/moderation/bans"
            f"?broadcaster_id={broadcaster_id}"
            f"&moderator_id={broadcaster_id}"
        )
        body = {
            "data": {
                "user_id": user_id,
                "duration": duration,
                "reason": "lizardroulette",
            }
        }

        response = await twitch_request(channel, "POST", url, json=body)
        if response is None:
            logger.warning(
                "Failed to timeout user %s in #%s (no response)",
                user_id,
                channel.twitch_channel_name,
            )
            return False

        if response.status_code >= 400:
            logger.warning(
                "Timeout API returned %s for user %s in #%s",
                response.status_code,
                user_id,
                channel.twitch_channel_name,
            )
            return False

        return True


register_skill(LizardRouletteHandler())
