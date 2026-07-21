"""Audit and heal Synthfunc tenancy for every active channel.

For each active Channel: ensure the Synthfunc tenant exists, and if it
was just created (meaning the channel has been running half-onboarded),
push the locally-cached owner tokens so Synthfunc takes custody. This
is the operator version of what invite completion now does inline —
run it whenever tenancy drift is suspected.
"""

from __future__ import annotations

import asyncio

from asgiref.sync import sync_to_async
from django.core.management.base import BaseCommand

from core.models import Channel
from core.synthfunc import ensure_tenant
from core.synthfunc import save_token


class Command(BaseCommand):
    help = "Ensure every active channel has a Synthfunc tenant; heal token custody."

    def handle(self, *args, **options):
        asyncio.run(self._run())

    async def _run(self) -> None:
        channels = await sync_to_async(list)(
            Channel.objects.filter(is_active=True)
        )
        for channel in channels:
            slug = channel.twitch_channel_name
            result = await ensure_tenant(
                slug=slug,
                name=slug,
                twitch_id=channel.twitch_channel_id,
                twitch_username=slug,
            )
            if result is None:
                self.stdout.write(self.style.ERROR(f"  #{slug}: ensure FAILED"))
                continue

            created = result.get("created")
            self.stdout.write(
                self.style.SUCCESS(
                    f"  #{slug}: tenant {'PROVISIONED' if created else 'ok'}"
                )
            )

            if created and channel.owner_access_token:
                pushed = await save_token(
                    user_id=channel.twitch_channel_id,
                    access_token=channel.owner_access_token,
                    refresh_token=channel.owner_refresh_token,
                    expires_in=0,
                )
                if pushed:
                    self.stdout.write(
                        self.style.SUCCESS(f"  #{slug}: owner tokens pushed")
                    )
                else:
                    self.stdout.write(
                        self.style.ERROR(f"  #{slug}: token push FAILED")
                    )
