from __future__ import annotations

import logging

from asgiref.sync import sync_to_async
from django.db.models import F

from bot.skills import SkillHandler
from bot.skills import register_skill

logger = logging.getLogger("bot")


class CounterHandler(SkillHandler):
    """Named counters — death count, scare count, etc.

    Subcommand interface:
        !count <name>              — Show counter value
        !count <name> +            — Increment (mod/broadcaster)
        !count <name> -            — Decrement (mod/broadcaster)
        !count <name> set <N>      — Set to value (mod/broadcaster)

    Counter state is stored in the Counter model, not Skill.config.
    """

    name = "count"

    async def handle(self, payload, args, skill):
        parts = args.split() if args else []
        if not parts:
            await payload.respond("Usage: !count <name> [+|-|set <N>]")
            return

        counter_name = parts[0].lower()
        action = parts[1] if len(parts) > 1 else None
        broadcaster_id = str(payload.broadcaster.id)

        from core.models import Counter

        if action in ("+", "-", "set"):
            # Mutation requires mod/broadcaster
            chatter = payload.chatter
            if not chatter or (not chatter.moderator and not chatter.broadcaster):
                return

            if action == "set":
                if len(parts) < 3:
                    await payload.respond("Usage: !count <name> set <N>")
                    return
                try:
                    new_value = int(parts[2])
                except ValueError:
                    await payload.respond("Value must be a number.")
                    return

                counter, created = await sync_to_async(
                    Counter.objects.update_or_create
                )(
                    channel__twitch_channel_id=broadcaster_id,
                    channel__is_active=True,
                    name=counter_name,
                    defaults={"value": new_value},
                )
                if created:
                    # Need to set the channel FK when creating
                    from core.models import Channel

                    channel = await sync_to_async(Channel.objects.get)(
                        twitch_channel_id=broadcaster_id, is_active=True
                    )
                    counter.channel = channel
                    await sync_to_async(counter.save)(update_fields=["channel_id"])

                label = counter.label or counter.name.title()
                await payload.respond(f"{label}: {new_value}")
                return

            # Increment or decrement
            delta = 1 if action == "+" else -1

            from core.models import Channel

            channel = await sync_to_async(Channel.objects.get)(
                twitch_channel_id=broadcaster_id, is_active=True
            )

            counter, created = await sync_to_async(
                Counter.objects.get_or_create
            )(
                channel=channel,
                name=counter_name,
                defaults={"value": 0},
            )

            # Atomic update
            await sync_to_async(
                Counter.objects.filter(pk=counter.pk).update
            )(value=F("value") + delta)

            # Refresh to get the updated value
            await sync_to_async(counter.refresh_from_db)()
            label = counter.label or counter.name.title()
            await payload.respond(f"{label}: {counter.value}")
            return

        # No action — show the counter value
        try:
            counter = await sync_to_async(Counter.objects.get)(
                channel__twitch_channel_id=broadcaster_id,
                channel__is_active=True,
                name=counter_name,
            )
        except Counter.DoesNotExist:
            await payload.respond(f"Counter '{counter_name}' does not exist.")
            return

        label = counter.label or counter.name.title()
        await payload.respond(f"{label}: {counter.value}")


register_skill(CounterHandler())
