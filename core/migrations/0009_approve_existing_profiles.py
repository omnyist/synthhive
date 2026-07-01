from __future__ import annotations

from django.db import migrations


def approve_existing_profiles(apps, schema_editor):
    TwitchProfile = apps.get_model("core", "TwitchProfile")
    TwitchProfile.objects.filter(is_approved=False).update(is_approved=True)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0008_add_invite_and_is_approved"),
    ]

    operations = [
        migrations.RunPython(
            approve_existing_profiles,
            migrations.RunPython.noop,
        ),
    ]
