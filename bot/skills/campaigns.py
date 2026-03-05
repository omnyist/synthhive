"""!campaign — Campaign commands powered by Synthfunc.

Usage:
    !campaign           — Show active campaign info
    !timer              — Show timer status
    !milestones         — Show milestone progress
    !gifts              — Show top gift contributors
"""

from __future__ import annotations

import logging
from datetime import UTC
from datetime import datetime

from bot.router import send_reply
from bot.skills import SkillHandler
from bot.skills import register_skill
from core.synthfunc import get_active_campaign
from core.synthfunc import get_gift_leaderboard
from core.synthfunc import pause_campaign_timer
from core.synthfunc import start_campaign_timer

logger = logging.getLogger("bot")


class CampaignHandler(SkillHandler):
    """!campaign — Show active campaign info."""

    name = "campaign"

    async def handle(self, payload, args, skill, bot):
        tenant_slug = skill.channel.twitch_channel_name
        campaign = await get_active_campaign(tenant_slug)
        if not campaign:
            await send_reply(
                payload,
                "No active campaign right now.",
                bot_id=bot.bot_id,
            )
            return

        name = campaign.get("name", "Unknown")
        metric = campaign.get("metric", {})
        total_subs = metric.get("total_subs", 0)
        total_resubs = metric.get("total_resubs", 0)

        milestones = campaign.get("milestones", [])
        unlocked = sum(1 for m in milestones if m.get("is_unlocked"))
        total_milestones = len(milestones)

        parts = [f"{name}: {total_subs} subs, {total_resubs} resubs"]
        if total_milestones > 0:
            parts.append(f"{unlocked}/{total_milestones} milestones unlocked")

        await send_reply(
            payload, " | ".join(parts), bot_id=bot.bot_id
        )


class TimerHandler(SkillHandler):
    """!timer — Show subathon timer status."""

    name = "timer"

    async def handle(self, payload, args, skill, bot):
        tenant_slug = skill.channel.twitch_channel_name
        campaign = await get_active_campaign(tenant_slug)
        if not campaign:
            await send_reply(
                payload,
                "No active campaign right now.",
                bot_id=bot.bot_id,
            )
            return

        if campaign.get("timer_mode") != "countdown":
            await send_reply(
                payload,
                "This campaign doesn't have a timer.",
                bot_id=bot.bot_id,
            )
            return

        metric = campaign.get("metric", {})
        remaining = metric.get("timer_seconds_remaining", 0)
        started_at = metric.get("timer_started_at")
        paused_at = metric.get("timer_paused_at")

        if paused_at:
            status = "PAUSED"
        elif started_at:
            status = "RUNNING"
        else:
            status = "NOT STARTED"

        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        seconds = remaining % 60

        if hours > 0:
            time_str = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            time_str = f"{minutes}m {seconds}s"
        else:
            time_str = f"{seconds}s"

        await send_reply(
            payload,
            f"Timer: {time_str} remaining ({status})",
            bot_id=bot.bot_id,
        )


class MilestonesHandler(SkillHandler):
    """!milestones — Show milestone progress."""

    name = "milestones"

    async def handle(self, payload, args, skill, bot):
        tenant_slug = skill.channel.twitch_channel_name
        campaign = await get_active_campaign(tenant_slug)
        if not campaign:
            await send_reply(
                payload,
                "No active campaign right now.",
                bot_id=bot.bot_id,
            )
            return

        milestones = campaign.get("milestones", [])
        if not milestones:
            await send_reply(
                payload,
                "No milestones set for this campaign.",
                bot_id=bot.bot_id,
            )
            return

        parts = []
        for m in milestones:
            icon = "+" if m.get("is_unlocked") else "-"
            parts.append(f"[{icon}] {m['title']} ({m['threshold']})")

        await send_reply(
            payload, " ".join(parts), bot_id=bot.bot_id
        )


class GiftsHandler(SkillHandler):
    """!gifts — Show top gift sub contributors."""

    name = "gifts"

    async def handle(self, payload, args, skill, bot):
        tenant_slug = skill.channel.twitch_channel_name
        leaderboard = await get_gift_leaderboard(tenant_slug, limit=5)
        if not leaderboard:
            await send_reply(
                payload,
                "No gift data available.",
                bot_id=bot.bot_id,
            )
            return

        parts = []
        for i, entry in enumerate(leaderboard, 1):
            name = entry.get("display_name", entry.get("username", "???"))
            total = entry.get("total_count", 0)
            parts.append(f"{i}. {name} ({total})")

        await send_reply(
            payload,
            f"Top gifters: {', '.join(parts)}",
            bot_id=bot.bot_id,
        )


class NextGoalHandler(SkillHandler):
    """!nextgoal — Show the next milestone to unlock."""

    name = "nextgoal"

    async def handle(self, payload, args, skill, bot):
        tenant_slug = skill.channel.twitch_channel_name
        campaign = await get_active_campaign(tenant_slug)
        if not campaign:
            await send_reply(
                payload, "No active campaign right now.", bot_id=bot.bot_id
            )
            return

        milestones = campaign.get("milestones", [])
        next_milestone = None
        for m in milestones:
            if not m.get("is_unlocked"):
                next_milestone = m
                break

        if not next_milestone:
            await send_reply(
                payload, "All milestones unlocked!", bot_id=bot.bot_id
            )
            return

        await send_reply(
            payload,
            f"Next goal: {next_milestone['title']} at {next_milestone['threshold']}",
            bot_id=bot.bot_id,
        )


class ProgressHandler(SkillHandler):
    """!progress — Show overall campaign progress."""

    name = "progress"

    async def handle(self, payload, args, skill, bot):
        tenant_slug = skill.channel.twitch_channel_name
        campaign = await get_active_campaign(tenant_slug)
        if not campaign:
            await send_reply(
                payload, "No active campaign right now.", bot_id=bot.bot_id
            )
            return

        metric = campaign.get("metric", {})
        total_subs = metric.get("total_subs", 0)
        total_resubs = metric.get("total_resubs", 0)
        total_bits = metric.get("total_bits", 0)

        milestones = campaign.get("milestones", [])
        unlocked = sum(1 for m in milestones if m.get("is_unlocked"))
        total = len(milestones)
        pct = int((unlocked / total * 100)) if total > 0 else 0

        parts = [f"Progress: {pct}% ({unlocked}/{total} milestones)"]
        parts.append(f"{total_subs} subs, {total_resubs} resubs")
        if total_bits > 0:
            parts.append(f"{total_bits:,} bits")

        await send_reply(
            payload, " | ".join(parts), bot_id=bot.bot_id
        )


class StartTimerHandler(SkillHandler):
    """!starttimer — Start the subathon timer (mod/broadcaster only)."""

    name = "starttimer"

    async def handle(self, payload, args, skill, bot):
        chatter = payload.chatter
        if not chatter or not (chatter.moderator or chatter.broadcaster):
            return

        tenant_slug = skill.channel.twitch_channel_name
        result = await start_campaign_timer(tenant_slug)
        if not result or result.get("error"):
            error = result.get("error", "Unknown error") if result else "No response"
            await send_reply(
                payload, f"Failed to start timer: {error}", bot_id=bot.bot_id
            )
            return

        await send_reply(payload, "Timer started!", bot_id=bot.bot_id)


class PauseTimerHandler(SkillHandler):
    """!pausetimer — Pause the subathon timer (mod/broadcaster only)."""

    name = "pausetimer"

    async def handle(self, payload, args, skill, bot):
        chatter = payload.chatter
        if not chatter or not (chatter.moderator or chatter.broadcaster):
            return

        tenant_slug = skill.channel.twitch_channel_name
        result = await pause_campaign_timer(tenant_slug)
        if not result or result.get("error"):
            error = result.get("error", "Unknown error") if result else "No response"
            await send_reply(
                payload, f"Failed to pause timer: {error}", bot_id=bot.bot_id
            )
            return

        await send_reply(payload, "Timer paused!", bot_id=bot.bot_id)


register_skill(CampaignHandler())
register_skill(TimerHandler())
register_skill(MilestonesHandler())
register_skill(GiftsHandler())
register_skill(NextGoalHandler())
register_skill(ProgressHandler())
register_skill(StartTimerHandler())
register_skill(PauseTimerHandler())
