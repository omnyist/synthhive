from __future__ import annotations

from django.db import migrations

COUNTER_KEYS = [
    "plays",
    "deaths",
    "survivals",
    "streak",
    "max_streak",
    "bullet_deaths",
    "streaks_broken",
]


def backfill_columns(apps, schema_editor):
    """Copy counter stats from the JSON blob into the real columns,
    then strip the migrated keys so there's one source of truth."""
    SkillStat = apps.get_model("core", "SkillStat")

    for stat in SkillStat.objects.all():
        blob = stat.stats or {}
        for key in COUNTER_KEYS:
            setattr(stat, key, int(blob.pop(key, 0) or 0))
        stat.last_mood = str(blob.pop("last_mood", "") or "")
        stat.stats = blob
        stat.save(
            update_fields=[*COUNTER_KEYS, "last_mood", "stats"]
        )


def restore_json(apps, schema_editor):
    """Reverse: copy columns back into the JSON blob."""
    SkillStat = apps.get_model("core", "SkillStat")

    for stat in SkillStat.objects.all():
        blob = stat.stats or {}
        for key in COUNTER_KEYS:
            blob[key] = getattr(stat, key)
        if stat.last_mood:
            blob["last_mood"] = stat.last_mood
        stat.stats = blob
        stat.save(update_fields=["stats"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_skillstat_real_columns"),
    ]

    operations = [
        migrations.RunPython(backfill_columns, restore_json),
    ]
