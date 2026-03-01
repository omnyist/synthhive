from __future__ import annotations

import secrets
import string

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand

from core.models import Bot
from core.models import Channel

SEED_DATA = {
    "users": [
        {
            "username": "avalonstar",
            "is_superuser": True,
            "is_staff": True,
        },
        {
            "username": "spoonee",
            "is_superuser": False,
            "is_staff": True,
        },
    ],
    "bots": [
        {
            "name": "Elsydeon",
            "twitch_user_id": "66977097",
            "twitch_username": "elsydeon",
            "channels": [
                {
                    "twitch_channel_id": "38981465",
                    "twitch_channel_name": "avalonstar",
                },
            ],
        },
        {
            "name": "WorldFriendshipBot",
            "twitch_user_id": "149214941",
            "twitch_username": "worldfriendshipbot",
            "channels": [
                {
                    "twitch_channel_id": "78238052",
                    "twitch_channel_name": "spoonee",
                },
            ],
        },
    ],
}


def generate_password(length: int = 16) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


class Command(BaseCommand):
    help = "Seed initial users, bots, and channels."

    def handle(self, *args, **options):
        self.stdout.write(self.style.MIGRATE_HEADING("Seeding database..."))

        for user_data in SEED_DATA["users"]:
            username = user_data["username"]
            user, created = User.objects.get_or_create(
                username=username,
                defaults={
                    "is_superuser": user_data["is_superuser"],
                    "is_staff": user_data["is_staff"],
                },
            )

            if created:
                password = generate_password()
                user.set_password(password)
                user.save()
                role = "superuser" if user_data["is_superuser"] else "staff"
                self.stdout.write(
                    self.style.SUCCESS(
                        f"  Created {role} user: {username} (password: {password})"
                    )
                )
            else:
                self.stdout.write(f"  User already exists: {username}")

        for bot_data in SEED_DATA["bots"]:
            bot, created = Bot.objects.get_or_create(
                twitch_user_id=bot_data["twitch_user_id"],
                defaults={
                    "name": bot_data["name"],
                    "twitch_username": bot_data["twitch_username"],
                },
            )

            status = "Created" if created else "Exists"
            self.stdout.write(
                self.style.SUCCESS(f"  {status} bot: {bot.name} ({bot.twitch_user_id})")
            )

            for ch_data in bot_data["channels"]:
                channel, ch_created = Channel.objects.get_or_create(
                    bot=bot,
                    twitch_channel_id=ch_data["twitch_channel_id"],
                    defaults={
                        "twitch_channel_name": ch_data["twitch_channel_name"],
                    },
                )

                status = "Created" if ch_created else "Exists"
                self.stdout.write(
                    self.style.SUCCESS(
                        f"    {status} channel: #{channel.twitch_channel_name}"
                    )
                )

        self.stdout.write(self.style.SUCCESS("\nSeed complete."))
        self.stdout.write(
            "Next: visit /setup/<bot_id>/ to connect bot and channel tokens."
        )
