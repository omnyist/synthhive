from __future__ import annotations

import asyncio
import logging
import random
import time

from asgiref.sync import sync_to_async

from bot.router import send_reply
from bot.skills import SkillHandler
from bot.skills import register_skill
from bot.skills.lizardmood import MOOD_BEHAVIORS
from bot.skills.lizardmood import MoodContext
from bot.skills.lizardmood import render_death
from bot.skills.lizardmood import render_survival
from bot.skills.lizardmood import roll_mood
from bot.skills.lizardmood import DeathMessage
from core.twitch import TWITCH_API_BASE
from core.twitch import twitch_request

logger = logging.getLogger("bot")


CHEMICALS = [
    "serotonin",
    "dopamine",
    "oxytocin",
    "endorphins",
    "copium",
    "hopium",
    "adrenaline",
    "melatonin",
    "norepinephrine",
]


class LizardRouletteHandler(SkillHandler):
    """!lizardroulette — Roll the dice. Lose and get timed out."""

    name = "lizardroulette"

    def __init__(self):
        self._cooldowns: dict[str, float] = {}
        self._bullets: dict[str, int] = {}
        self._last_victim: dict[str, str] = {}

    async def handle(self, payload, args, skill, bot):
        chatter = payload.chatter
        if not chatter:
            return

        broadcaster_id = str(payload.broadcaster.id)
        chatter_id = str(chatter.id)
        chatter_name = chatter.display_name
        config = skill.config or {}

        # --- Per-user cooldown (scoped to channel) ---
        cooldown = config.get("cooldown", 300)
        now = time.monotonic()
        cooldown_key = f"{broadcaster_id}:{chatter_id}"
        last_used = self._cooldowns.get(cooldown_key)
        if last_used and (now - last_used) < cooldown:
            cooldown_response = config.get("cooldown_response")
            if cooldown_response:
                remaining = int(cooldown - (now - last_used))
                message = cooldown_response.replace(
                    "$(user)", chatter_name
                ).replace("$(remaining)", str(remaining))
                await send_reply(payload, message, bot_id=bot.bot_id)
            return

        self._cooldowns[cooldown_key] = now

        # --- Look up channel for stat tracking ---
        from core.models import Channel

        try:
            channel = await sync_to_async(Channel.objects.get)(
                twitch_channel_id=broadcaster_id,
                is_active=True,
            )
        except Channel.DoesNotExist:
            logger.warning("No active channel found for broadcaster %s", broadcaster_id)
            return

        # --- Track play count ---
        await self._update_stat(channel, chatter_id, chatter.name, "plays")

        # --- Check for loaded gun ---
        bullets = self._bullets.get(broadcaster_id, 0)
        if bullets > 0:
            self._bullets[broadcaster_id] = bullets - 1
            is_loss = True
            was_bullet = True
        else:
            odds = config.get("odds", 16)
            is_loss = random.randint(1, 100) <= odds
            was_bullet = False

        # --- Resolve outcome ---
        if is_loss:
            deaths = await self._update_stat(
                channel, chatter_id, chatter.name, "deaths"
            )
            broken_streak = await self._get_stat(channel, chatter_id, "streak")
            await self._set_stat(channel, chatter_id, chatter.name, "streak", 0)
            previous_victim = self._last_victim.get(broadcaster_id, "")
            self._last_victim[broadcaster_id] = chatter_name

            if was_bullet:
                await self._update_stat(
                    channel, chatter_id, chatter.name, "bullet_deaths"
                )
            if broken_streak > 0:
                await self._update_stat(
                    channel, chatter_id, chatter.name, "streaks_broken"
                )

            ctx = MoodContext(
                outcome="death",
                deaths=deaths,
                streak=broken_streak,
                max_streak=await self._get_stat(channel, chatter_id, "max_streak"),
                chatter_name=chatter_name,
                victim=previous_victim,
                is_self_victim=(previous_victim == chatter_name),
                bullets_loaded=was_bullet,
                chemical="",
                channel_id=broadcaster_id,
                rival=await self._get_rival(channel, chatter_id),
            )
            mood_roll = roll_mood(ctx)
            behavior = MOOD_BEHAVIORS[mood_roll.mood]
            logger.debug(
                "[LizardRoulette] mood=%s weights=%s user=%s deaths=%d",
                mood_roll.mood.value,
                {k.value: v for k, v in mood_roll.weights.items()},
                chatter_name,
                deaths,
            )

            await self._set_stat(
                channel, chatter_id, chatter.name,
                "last_mood", mood_roll.mood.value,
            )

            death_msg = render_death(mood_roll.mood, ctx)
            timeout_delay = config.get("timeout_delay", 5) * behavior.timeout_delay_multiplier
            timeout_duration = config.get("timeout_duration", 600)

            if death_msg.timeout_first:
                # Shoot first, talk later.
                timed_out = await self._timeout_user(
                    channel, broadcaster_id, chatter_id, timeout_duration
                )
                logger.info(
                    "[LizardRoulette] Timeout (first): user=%s success=%s",
                    chatter_name,
                    timed_out,
                )
                await send_reply(payload, death_msg.text, bot_id=bot.bot_id)
            else:
                await send_reply(payload, death_msg.text, bot_id=bot.bot_id)
                logger.info(
                    "[LizardRoulette] Timeout pending: user=%s delay=%.1fs duration=%ds",
                    chatter_name,
                    timeout_delay,
                    timeout_duration,
                )
                await asyncio.sleep(timeout_delay)
                timed_out = await self._timeout_user(
                    channel, broadcaster_id, chatter_id, timeout_duration
                )
                logger.info(
                    "[LizardRoulette] Timeout result: user=%s success=%s",
                    chatter_name,
                    timed_out,
                )

            if not timed_out:
                timeout_failed = config.get("timeout_failed")
                if timeout_failed:
                    msg = timeout_failed.replace("$(user)", chatter_name)
                    await send_reply(payload, msg, bot_id=bot.bot_id)
        else:
            streak = await self._update_stat(
                channel, chatter_id, chatter.name, "streak"
            )
            await self._update_stat(
                channel, chatter_id, chatter.name, "survivals"
            )
            max_streak = await self._get_stat(channel, chatter_id, "max_streak")
            if streak > max_streak:
                await self._set_stat(
                    channel, chatter_id, chatter.name, "max_streak", streak
                )

            victim = self._last_victim.get(broadcaster_id, "")
            chemical = random.choice(CHEMICALS)

            ctx = MoodContext(
                outcome="survival",
                deaths=await self._get_stat(channel, chatter_id, "deaths"),
                streak=streak,
                max_streak=max(streak, max_streak),
                chatter_name=chatter_name,
                victim=victim,
                is_self_victim=(victim == chatter_name),
                bullets_loaded=self._bullets.get(broadcaster_id, 0) > 0,
                chemical=chemical,
                channel_id=broadcaster_id,
                rival=await self._get_rival(channel, chatter_id),
            )
            mood_roll = roll_mood(ctx)
            logger.debug(
                "[LizardRoulette] mood=%s weights=%s user=%s streak=%d",
                mood_roll.mood.value,
                {k.value: v for k, v in mood_roll.weights.items()},
                chatter_name,
                streak,
            )

            await self._set_stat(
                channel, chatter_id, chatter.name,
                "last_mood", mood_roll.mood.value,
            )

            message = render_survival(mood_roll.mood, ctx)
            await send_reply(payload, message, bot_id=bot.bot_id)

    async def _get_rival(self, channel, exclude_id: str) -> str:
        """Pick a random rival from the top 5 survivors, excluding the current player."""
        from core.models import SkillStat

        stats = await sync_to_async(list)(
            SkillStat.objects.filter(
                channel=channel,
                skill_name="lizardroulette",
            ).exclude(twitch_id=exclude_id)
        )
        top = sorted(
            [s for s in stats if s.stats.get("max_streak", 0) > 0],
            key=lambda s: s.stats.get("max_streak", 0),
            reverse=True,
        )[:5]
        if not top:
            return ""
        return random.choice(top).twitch_username

    async def _get_stat(self, channel, twitch_id, stat_key):
        """Read a stat value, returning 0 if not found."""
        from core.models import SkillStat

        try:
            stat = await sync_to_async(SkillStat.objects.get)(
                channel=channel,
                skill_name="lizardroulette",
                twitch_id=twitch_id,
            )
            return stat.stats.get(stat_key, 0)
        except SkillStat.DoesNotExist:
            return 0

    async def _set_stat(self, channel, twitch_id, username, stat_key, value):
        """Set a stat to a specific value."""
        from core.models import SkillStat

        stat, created = await sync_to_async(SkillStat.objects.get_or_create)(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id=twitch_id,
            defaults={"twitch_username": username, "stats": {stat_key: value}},
        )
        if not created:
            stat.twitch_username = username
            stat.stats[stat_key] = value
            await sync_to_async(stat.save)(update_fields=["twitch_username", "stats"])

    async def _update_stat(self, channel, twitch_id, username, stat_key):
        """Increment a stat and return the new value."""
        from core.models import SkillStat

        stat, created = await sync_to_async(SkillStat.objects.get_or_create)(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id=twitch_id,
            defaults={"twitch_username": username, "stats": {stat_key: 1}},
        )
        if not created:
            stat.twitch_username = username
            stat.stats[stat_key] = stat.stats.get(stat_key, 0) + 1
            await sync_to_async(stat.save)(update_fields=["twitch_username", "stats"])
        return stat.stats.get(stat_key, 1)

    async def _timeout_user(
        self,
        channel,
        broadcaster_id: str,
        user_id: str,
        duration: int,
    ) -> bool:
        """Issue a timeout via the Twitch Helix moderation API.

        Returns True if the timeout succeeded, False otherwise.
        """
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
                "Timeout API returned %s for user %s in #%s: %s",
                response.status_code,
                user_id,
                channel.twitch_channel_name,
                response.text,
            )
            return False

        return True


register_skill(LizardRouletteHandler())
