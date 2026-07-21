from __future__ import annotations

from django.db import migrations

# The pre-mood-era lizardroulette config carried success/failure/
# failure_first template keys the current handler never reads. With
# config now schema-validated (extra="forbid"), these vestigial keys
# would make every future edit of the row fail validation — prune them.
LEGACY_KEYS = ("success", "failure", "failure_first")


def prune(apps, schema_editor):
    Skill = apps.get_model("core", "Skill")
    for skill in Skill.objects.filter(name="lizardroulette"):
        config = skill.config or {}
        removed = [k for k in LEGACY_KEYS if config.pop(k, None) is not None]
        if removed:
            skill.config = config
            skill.save(update_fields=["config"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0017_lizard_play_message"),
    ]

    operations = [
        migrations.RunPython(prune, migrations.RunPython.noop),
    ]
