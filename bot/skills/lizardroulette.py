from __future__ import annotations

import asyncio
import logging
import random
import time
from collections import deque

from asgiref.sync import sync_to_async

from bot.router import send_reply
from bot.skills import SkillHandler
from bot.skills import register_skill
from bot.skills.lizardmood import MOOD_BEHAVIORS
from bot.skills.lizardmood import MoodContext
from bot.skills.lizardmood import render_death
from bot.skills.lizardmood import render_survival
from bot.skills.lizardmood import roll_mood
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

    INTERVAL_WINDOW = 3  # plays needed to detect scripting
    INTERVAL_TOLERANCE = 30  # seconds of variance allowed
    LIVE_CACHE_TTL = 60  # seconds to cache a channel's live status

    def __init__(self):
        self._cooldowns: dict[str, float] = {}
        self._bullets: dict[str, int] = {}
        self._last_victim: dict[str, str] = {}
        self._play_intervals: dict[str, deque[float]] = {}
        self._live_cache: dict[str, tuple[bool, float]] = {}

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

        # --- Track play intervals for scripting detection ---
        if last_used:
            interval = now - last_used
            intervals = self._play_intervals.setdefault(
                cooldown_key, deque(maxlen=self.INTERVAL_WINDOW)
            )
            intervals.append(interval)
        is_scripted = self._detect_scripted(cooldown_key)

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

        # --- Live status (cached) drives offline messaging + capture ---
        is_live = await self._is_live(channel, broadcaster_id)

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
                is_scripted=is_scripted,
                is_live=is_live,
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
            await self._record_play(
                channel, chatter_id, chatter.name, mood_roll, was_bullet
            )

            death_msg = render_death(mood_roll.mood, ctx)
            timeout_delay = config.get("timeout_delay", 5) * behavior.timeout_delay_multiplier
            timeout_duration = config.get("timeout_duration", 600)

            if death_msg.timeout_first:
                # Shoot first, talk later. Can't reply — the message
                # is deleted when the timeout fires.
                timed_out = await self._timeout_user(
                    channel, broadcaster_id, chatter_id, timeout_duration
                )
                logger.info(
                    "[LizardRoulette] Timeout (first): user=%s success=%s",
                    chatter_name,
                    timed_out,
                )
                await payload.broadcaster.send_message(
                    sender=bot.bot_id,
                    message=death_msg.text,
                )
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
                if chatter_id == broadcaster_id:
                    timeout_failed = config.get("timeout_failed")
                    if timeout_failed:
                        msg = timeout_failed.replace("$(user)", chatter_name)
                        await send_reply(payload, msg, bot_id=bot.bot_id)
                else:
                    logger.warning(
                        "[LizardRoulette] Timeout failed for non-broadcaster: user=%s channel=#%s",
                        chatter_name,
                        channel.twitch_channel_name,
                    )
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
                is_scripted=is_scripted,
                is_live=is_live,
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
            await self._record_play(
                channel, chatter_id, chatter.name, mood_roll, was_bullet=False
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

    async def _is_live(self, channel, broadcaster_id: str) -> bool:
        """Return whether the channel is currently live, cached per channel.

        A channel goes on/offline rarely, so a short TTL cache keeps play
        volume from hammering the Helix /streams endpoint.
        """
        cached = self._live_cache.get(broadcaster_id)
        now = time.monotonic()
        if cached and now < cached[1]:
            return cached[0]

        response = await twitch_request(
            channel,
            "GET",
            f"{TWITCH_API_BASE}/streams",
            params={"user_id": broadcaster_id},
        )
        if response is None or response.status_code != 200:
            # Unknown → assume live so we don't wrongly taunt during an
            # API blip. Don't cache failures.
            return True

        live = len(response.json().get("data", [])) > 0
        self._live_cache[broadcaster_id] = (live, now + self.LIVE_CACHE_TTL)
        return live

    async def _record_play(
        self, channel, twitch_id, username, mood_roll, was_bullet
    ) -> None:
        """Append a per-play record for analytics / ML training.

        Fire-and-forget: a capture failure must never break the game.
        """
        from dataclasses import asdict

        from core.models import LizardPlay

        ctx = mood_roll.ctx
        try:
            await sync_to_async(LizardPlay.objects.create)(
                channel=channel,
                twitch_id=twitch_id,
                twitch_username=username,
                outcome=ctx.outcome,
                was_bullet=was_bullet,
                is_scripted=ctx.is_scripted,
                is_live=ctx.is_live,
                mood=mood_roll.mood.value,
                mood_weights={m.value: w for m, w in mood_roll.weights.items()},
                deaths=ctx.deaths,
                streak=ctx.streak,
                max_streak=ctx.max_streak,
                context=asdict(ctx),
            )
        except Exception:
            logger.exception(
                "[LizardRoulette] Failed to record play for %s", username
            )

    def _detect_scripted(self, cooldown_key: str) -> bool:
        """Check if the player's recent play intervals are suspiciously consistent."""
        intervals = self._play_intervals.get(cooldown_key)
        if not intervals or len(intervals) < self.INTERVAL_WINDOW:
            return False
        avg = sum(intervals) / len(intervals)
        return all(abs(i - avg) <= self.INTERVAL_TOLERANCE for i in intervals)

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
