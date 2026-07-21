from __future__ import annotations

from django.db import migrations

# Code defaults for these skills went tenant-neutral (bard*/avalon*
# emotes and "spoons" removed). Freeze the historical flavored values
# into existing rows so nothing changes for the tenants that relied on
# the old defaults. Only keys the row does NOT already set are written.

LEGACY_DUNGEON_MESSAGES = {
    "outcome_wipe": (
        "The party boldly enters the Dungeon...but they are ill prepared. "
        "They barely make it past the first room when the entire party is MPKed... bardRIP "
        "It looks like $(level_name) knew they were coming. bardSad"
    ),
    "outcome_few": (
        "The party doesn't get far into the Dungeon when they are Back Attacked by the "
        "worst enemy of all...RNG! bardD Most of the party falls prey to RNG's clutches, "
        "but a few lucky survivors Flee and make it back to town safely."
    ),
    "outcome_most": (
        "Some of the party fall prey to Random Battles, but those who remain reach "
        "$(level_name)! They raise their Weapons of Magic and Might...and they scrape by! "
        "bardHype It was a rough fight. They resolve to exit the Dungeon and return another day."
    ),
    "outcome_all": (
        "The party reaches $(level_name)! They raise their Weapons of Magic and Might..."
        "and they are successful! bardHype The party is balanced well and ready for the fight. "
        "$(level_name) is clear (for now...)! Victory and treasure for all!"
    ),
    "outcome_solo_win": (
        "$(user) dares to enter $(level_name) alone...and they are successful! bardOMG "
        "$(user) sneaks in and out, looting treasure chests! Looted $(payout) $(currency)."
    ),
    "outcome_solo_loss": (
        "$(user) dares to enter $(level_name) alone...and they are unlucky! bardSad "
        "$(user) trips in the treasure room and finds an awakened Malboro. Game over. bardRIP"
    ),
    "results_losers": "Fallen: $(loser_list). bardRIP",
}

LEGACY_CUTE = {
    "bot_name": "elsydeon",
    "bot_response": "avalonREVERSE",
}

LEGACY_PUNT = {
    "immune": "/me can't punt $(user)! They're too kawaii~ avalonEYES",
    "success": "/me punted $(user) for their disrespect, lalafell hater. avalonRAGE",
}


def freeze_flavor(apps, schema_editor):
    Skill = apps.get_model("core", "Skill")

    for skill in Skill.objects.filter(name="dungeon"):
        config = skill.config or {}
        config.setdefault("currency_name", "spoons")
        messages = config.setdefault("messages", {})
        for key, value in LEGACY_DUNGEON_MESSAGES.items():
            messages.setdefault(key, value)
        skill.config = config
        skill.save(update_fields=["config"])

    for skill in Skill.objects.filter(name="cute"):
        config = skill.config or {}
        for key, value in LEGACY_CUTE.items():
            config.setdefault(key, value)
        skill.config = config
        skill.save(update_fields=["config"])

    for skill in Skill.objects.filter(name="punt"):
        config = skill.config or {}
        for key, value in LEGACY_PUNT.items():
            config.setdefault(key, value)
        skill.config = config
        skill.save(update_fields=["config"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_backfill_skillstat_columns"),
    ]

    operations = [
        migrations.RunPython(freeze_flavor, migrations.RunPython.noop),
    ]
