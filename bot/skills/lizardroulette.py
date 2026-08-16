from __future__ import annotations

import asyncio
import logging
import random
import time

from asgiref.sync import sync_to_async
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from bot import state
from bot.router import send_reply
from bot.skills import SkillHandler
from bot.skills import register_skill
from bot.skills.lizardmood import MOOD_BEHAVIORS
from bot.skills.lizardmood import MoodContext
from bot.skills.lizardmood import recency
from bot.skills.lizardmood import render_birthday
from bot.skills.lizardmood import render_death
from bot.skills.lizardmood import render_survival
from bot.skills.lizardmood import roll_mood
from bot.skills.lizardmood import roll_offline
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
    "gabapentin",
]


class LizardRouletteConfig(BaseModel):
    """Config schema — validated at every write path."""

    model_config = ConfigDict(extra="forbid")

    odds: int = Field(default=16, ge=1, le=100)
    cooldown: int = Field(default=300, ge=0)
    cooldown_response: str | None = None
    timeout_duration: int = Field(default=600, ge=1)
    timeout_delay: float = Field(default=5, ge=0)
    timeout_failed: str | None = None
    bullets_enabled: bool = True
    birthday_mode: bool = False


class LizardRouletteHandler(SkillHandler):
    """!lizardroulette — Roll the dice. Lose and get timed out."""

    name = "lizardroulette"
    config_schema = LizardRouletteConfig

    INTERVAL_WINDOW = 3  # plays needed to detect scripting
    INTERVAL_TOLERANCE = 30  # seconds of variance allowed
    LIVE_CACHE_TTL = 60  # seconds to cache a channel's live status

    def __init__(self):
        self._live_cache: dict[str, tuple[bool, float]] = {}

    async def handle(self, payload, args, skill, bot, channel):
        chatter = payload.chatter
        if not chatter:
            return

        broadcaster_id = str(payload.broadcaster.id)
        chatter_id = str(chatter.id)
        chatter_name = chatter.display_name
        config = skill.config or {}

        # --- Per-user cooldown (Redis, survives deploys) ---
        cooldown = config.get("cooldown", 300)
        cooldown_key = f"lr:cd:{broadcaster_id}:{chatter_id}"
        if not await state.cooldown_try_acquire(cooldown_key, cooldown):
            cooldown_response = config.get("cooldown_response")
            if cooldown_response:
                remaining = await state.cooldown_remaining(cooldown_key)
                message = cooldown_response.replace(
                    "$(user)", chatter_name
                ).replace("$(remaining)", str(remaining))
                await send_reply(payload, message, bot_id=bot.bot_id)
            return

        # --- Hydrate message-recency history for this channel ---
        await recency.hydrate(broadcaster_id)

        # --- Birthday mode: holster the gun, just celebrate ---
        if config.get("birthday_mode"):
            message = render_birthday(broadcaster_id, chatter_name)
            await recency.flush(broadcaster_id)
            await send_reply(payload, message, bot_id=bot.bot_id)
            return

        # --- Look up channel for stat tracking ---
        # --- Scripting detection from the play journal (survives deploys) ---
        is_scripted = await self._detect_scripted(channel, chatter_id)

        # --- Live status (cached) drives offline messaging + capture ---
        is_live = await self._is_live(channel, broadcaster_id)

        # --- Load this player's stats row (one read; values used below) ---
        stat = await self._get_or_create_stat(channel, chatter_id, chatter.name)

        # --- Check for loaded gun (Redis, survives deploys) ---
        bullets = await state.bullets_get(broadcaster_id)
        if bullets > 0:
            await state.bullets_decr(broadcaster_id)
            is_loss = True
            was_bullet = True
        else:
            odds = config.get("odds", 16)
            is_loss = random.randint(1, 100) <= odds
            was_bullet = False

        # --- Resolve outcome ---
        if is_loss:
            deaths = stat.deaths + 1
            broken_streak = stat.streak
            previous_victim = await state.victim_get(broadcaster_id)
            if not await state.victim_is_current(broadcaster_id):
                previous_victim = ""
            await state.victim_set(broadcaster_id, chatter_name)

            ctx = MoodContext(
                outcome="death",
                deaths=deaths,
                streak=broken_streak,
                max_streak=stat.max_streak,
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

            await self._apply_outcome(
                stat,
                chatter.name,
                mood=mood_roll.mood.value,
                death=True,
                was_bullet=was_bullet,
                broke_streak=broken_streak > 0,
            )
            offline_fragment, offline_tier = roll_offline(ctx)
            death_msg = render_death(
                mood_roll.mood, ctx, offline_fragment=offline_fragment
            )
            await recency.flush(broadcaster_id)
            await self._record_play(
                channel, chatter_id, chatter.name, mood_roll,
                was_bullet, offline_tier, message=death_msg.text,
            )
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
                # Journal the ban before the countdown — a deploy that
                # kills the process mid-sleep loses the asyncio task,
                # and LizardRecovery fires the journal at next startup.
                # The broadcaster can't be banned, so don't journal a
                # retry that could never succeed.
                if chatter_id != broadcaster_id:
                    await state.pending_timeout_add(
                        broadcaster_id,
                        chatter_id,
                        chatter_name,
                        timeout_duration,
                        due_at=time.time() + timeout_delay,
                    )
                await asyncio.sleep(timeout_delay)
                timed_out = await self._timeout_user(
                    channel, broadcaster_id, chatter_id, timeout_duration
                )
                if chatter_id != broadcaster_id:
                    await state.pending_timeout_clear(broadcaster_id, chatter_id)
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
            streak = stat.streak + 1
            max_streak = max(stat.max_streak, streak)

            await state.victim_bump(broadcaster_id)
            victim = await state.victim_get(broadcaster_id)
            if not await state.victim_is_current(broadcaster_id):
                victim = ""
            chemical = random.choice(CHEMICALS)

            ctx = MoodContext(
                outcome="survival",
                deaths=stat.deaths,
                streak=streak,
                max_streak=max_streak,
                chatter_name=chatter_name,
                victim=victim,
                is_self_victim=(victim == chatter_name),
                bullets_loaded=False,  # survival implies no bullet was chambered
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

            await self._apply_outcome(
                stat, chatter.name, mood=mood_roll.mood.value, death=False
            )
            offline_fragment, offline_tier = roll_offline(ctx)
            message = render_survival(
                mood_roll.mood, ctx, offline_fragment=offline_fragment
            )
            await recency.flush(broadcaster_id)
            await self._record_play(
                channel, chatter_id, chatter.name, mood_roll,
                was_bullet=False, offline_tier=offline_tier, message=message,
            )
            await send_reply(payload, message, bot_id=bot.bot_id)

    async def _get_rival(self, channel, exclude_id: str) -> str:
        """Pick a random rival from the top 5 survivors, excluding the current player."""
        from core.models import SkillStat

        top = await sync_to_async(list)(
            SkillStat.objects.filter(
                channel=channel,
                skill_name="lizardroulette",
                max_streak__gt=0,
            )
            .exclude(twitch_id=exclude_id)
            .order_by("-max_streak")
            .values_list("twitch_username", flat=True)[:5]
        )
        if not top:
            return ""
        return random.choice(top)

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
        self, channel, twitch_id, username, mood_roll, was_bullet,
        offline_tier="none", message="",
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
                offline_tier=offline_tier,
                mood=mood_roll.mood.value,
                message=message,
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

    async def _detect_scripted(self, channel, twitch_id: str) -> bool:
        """Check if recent play intervals are suspiciously consistent.

        Derived from the LizardPlay journal rather than an in-memory dict,
        so detection survives deploys instead of resetting every merge.
        """
        from core.models import LizardPlay

        timestamps = await sync_to_async(list)(
            LizardPlay.objects.filter(channel=channel, twitch_id=twitch_id)
            .order_by("-created_at")
            .values_list("created_at", flat=True)[: self.INTERVAL_WINDOW + 1]
        )
        if len(timestamps) < self.INTERVAL_WINDOW + 1:
            return False
        intervals = [
            (timestamps[i] - timestamps[i + 1]).total_seconds()
            for i in range(self.INTERVAL_WINDOW)
        ]
        avg = sum(intervals) / len(intervals)
        return all(abs(i - avg) <= self.INTERVAL_TOLERANCE for i in intervals)

    async def _get_or_create_stat(self, channel, twitch_id, username):
        """Fetch this player's stats row (creating it on first play)."""
        from core.models import SkillStat

        stat, _ = await sync_to_async(SkillStat.objects.get_or_create)(
            channel=channel,
            skill_name="lizardroulette",
            twitch_id=twitch_id,
            defaults={"twitch_username": username},
        )
        return stat

    async def _apply_outcome(
        self,
        stat,
        username: str,
        *,
        mood: str,
        death: bool,
        was_bullet: bool = False,
        broke_streak: bool = False,
    ) -> None:
        """Persist a play's outcome in one atomic queryset update.

        F() expressions make the increments race-safe; Greatest keeps
        max_streak correct without a read-modify-write.
        """
        from django.db.models import F
        from django.db.models.functions import Greatest

        from core.models import SkillStat

        updates = {
            "plays": F("plays") + 1,
            "last_mood": mood,
            "twitch_username": username,
        }
        if death:
            updates["deaths"] = F("deaths") + 1
            updates["streak"] = 0
            if was_bullet:
                updates["bullet_deaths"] = F("bullet_deaths") + 1
            if broke_streak:
                updates["streaks_broken"] = F("streaks_broken") + 1
        else:
            updates["survivals"] = F("survivals") + 1
            updates["max_streak"] = Greatest(F("max_streak"), F("streak") + 1)
            updates["streak"] = F("streak") + 1

        await sync_to_async(
            SkillStat.objects.filter(pk=stat.pk).update
        )(**updates)

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
