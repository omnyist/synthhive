from __future__ import annotations

import logging

import twitchio
from asgiref.sync import sync_to_async
from twitchio.ext import commands

from .skills import SKILL_REGISTRY
from .skills import discover_skills
from .variables import VariableContext
from .variables import create_registry

logger = logging.getLogger("bot")

# Commands handled by ManagementCommands — skip in the router
BUILTIN_COMMANDS = frozenset(
    {
        "addcom",
        "editcom",
        "delcom",
        "commands",
        "id",
        "alias",
        "unalias",
        "aliases",
        "counters",
    }
)


class CommandRouter(commands.Component):
    """Unified message handler for aliases, skills, and text commands.

    Replaces DynamicCommands with a single event_message listener that
    processes messages in this order:

    1. Self-message guard
    2. Prefix check (!)
    3. Skip built-in management commands
    4. Alias resolution (rewrites trigger to target)
    5. Skill dispatch (Python-coded handlers)
    6. Text command fallback (DB-defined responses)
    """

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._registry = create_registry()
        discover_skills()

    @commands.Component.listener()
    async def event_message(self, payload: twitchio.ChatMessage) -> None:
        # 1. Self-message guard
        if payload.chatter and str(payload.chatter.id) == str(self.bot.bot_id):
            return

        text = payload.text.strip()
        if not text.startswith("!"):
            return

        parts = text[1:].split(maxsplit=1)
        if not parts:
            return

        cmd_name = parts[0].lower()
        raw_args = parts[1] if len(parts) > 1 else ""

        # 3. Skip built-in commands
        if cmd_name in BUILTIN_COMMANDS:
            return

        broadcaster_id = str(payload.broadcaster.id)

        # 4. Alias resolution
        from core.models import Alias

        try:
            alias = await sync_to_async(Alias.objects.get)(
                channel__twitch_channel_id=broadcaster_id,
                channel__is_active=True,
                name=cmd_name,
            )
            # Rewrite: alias target may include args (e.g., "count death")
            alias_parts = alias.target.split(maxsplit=1)
            cmd_name = alias_parts[0].lower()
            # Prepend alias args before user args
            alias_args = alias_parts[1] if len(alias_parts) > 1 else ""
            if alias_args and raw_args:
                raw_args = f"{alias_args} {raw_args}"
            elif alias_args:
                raw_args = alias_args
        except Alias.DoesNotExist:
            pass

        # 5. Skill dispatch
        if cmd_name in SKILL_REGISTRY:
            from core.models import Skill

            try:
                skill = await sync_to_async(Skill.objects.get)(
                    channel__twitch_channel_id=broadcaster_id,
                    channel__is_active=True,
                    name=cmd_name,
                    enabled=True,
                )
            except Skill.DoesNotExist:
                return

            handler = SKILL_REGISTRY[cmd_name]
            try:
                await handler.handle(payload, raw_args, skill)
            except Exception:
                logger.exception(
                    "Skill handler '%s' failed",
                    cmd_name,
                )
            return

        # 6. Text command fallback
        from core.models import Command

        try:
            cmd = await sync_to_async(Command.objects.get)(
                channel__twitch_channel_id=broadcaster_id,
                channel__is_active=True,
                name=cmd_name,
                enabled=True,
            )
        except Command.DoesNotExist:
            return

        # Increment use count
        cmd.use_count += 1
        await sync_to_async(cmd.save)(update_fields=["use_count"])

        chatter_name = payload.chatter.name if payload.chatter else "someone"
        channel_name = payload.broadcaster.name if payload.broadcaster else ""

        # Extract target (first argument with @ stripped)
        target_arg = raw_args.split()[0].lstrip("@") if raw_args else chatter_name

        context = VariableContext(
            user=chatter_name,
            target=target_arg,
            channel_name=channel_name,
            broadcaster_id=broadcaster_id,
            command_name=cmd_name,
            use_count=cmd.use_count,
            raw_args=raw_args,
        )

        response = await self._registry.process(cmd.response, context)

        # Handle /me action messages
        use_me = False
        if response.startswith("/me "):
            use_me = True
            response = response[4:]
            # Strip the common "- " separator from Spoonee's commands
            if response.startswith("- "):
                response = response[2:]

        await payload.respond(response, me=use_me)
