"""!give — Transfer currency to another user.

Usage:
    !give @kefka 100  — Transfer 100 spoons to kefka
"""

from __future__ import annotations

import logging

from bot.router import send_reply
from bot.skills import SkillHandler
from bot.skills import register_skill
from core.synthfunc import get_wallet
from core.synthfunc import transact_wallets

logger = logging.getLogger("bot")


class GiveHandler(SkillHandler):
    """!give — Transfer currency between users."""

    name = "give"

    async def handle(self, payload, args, skill, bot):
        chatter = payload.chatter
        if not chatter:
            return

        tenant_slug = skill.channel.twitch_channel_name

        parts = args.strip().split() if args else []
        if len(parts) < 2:
            await send_reply(
                payload,
                "Usage: !give @user amount",
                bot_id=bot.bot_id,
            )
            return

        target_name = parts[0].lstrip("@").lower()
        try:
            amount = int(parts[1])
        except ValueError:
            await send_reply(
                payload,
                "Woah there, the amount must be a whole number.",
                bot_id=bot.bot_id,
            )
            return

        if amount <= 0:
            await send_reply(
                payload,
                "You trying to rob somebody? The amount must be positive.",
                bot_id=bot.bot_id,
            )
            return

        # Prevent self-transfer
        sender_name = chatter.name.lower() if chatter.name else ""
        if target_name == sender_name:
            await send_reply(
                payload,
                "You can't give currency to yourself, silly.",
                bot_id=bot.bot_id,
            )
            return

        # Resolve target Twitch user
        try:
            users = await bot.fetch_users(logins=[target_name])
        except Exception:
            logger.exception("Failed to fetch Twitch user: %s", target_name)
            await send_reply(
                payload,
                f"I don't know who {target_name} is.",
                bot_id=bot.bot_id,
            )
            return

        if not users:
            await send_reply(
                payload,
                f"I don't know who {target_name} is.",
                bot_id=bot.bot_id,
            )
            return

        target_user = users[0]
        target_id = str(target_user.id)
        target_display = target_user.display_name or target_name

        sender_id = str(chatter.id)
        sender_display = chatter.display_name or sender_name

        # Get currency name from sender's wallet
        wallet = await get_wallet(sender_id, tenant_slug, username=sender_name)
        currency = wallet.get("currency_name", "points") if wallet else "points"

        # Atomic debit sender + credit target
        result = await transact_wallets(
            tenant_slug,
            [
                {
                    "twitch_id": sender_id,
                    "amount": str(-amount),
                    "username": sender_name,
                    "display_name": sender_display,
                },
                {
                    "twitch_id": target_id,
                    "amount": str(amount),
                    "username": target_user.name or target_name,
                    "display_name": target_display,
                },
            ],
            reason="give",
        )

        if result is None:
            await send_reply(
                payload,
                "Transfer failed. Try again later.",
                bot_id=bot.bot_id,
            )
            return

        failed = result.get("failed", [])
        if failed:
            error = failed[0].get("error", "")
            if error == "insufficient_funds":
                await send_reply(
                    payload,
                    f"You don't have enough {currency}, them's the rules.",
                    bot_id=bot.bot_id,
                )
            else:
                await send_reply(
                    payload,
                    "Transfer failed. Try again later.",
                    bot_id=bot.bot_id,
                )
            return

        await send_reply(
            payload,
            f"transferred {amount:,} {currency} from {sender_display} to {target_display}.",
            bot_id=bot.bot_id,
            me=True,
        )


register_skill(GiveHandler())
