import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.RenameModel(
            old_name="CodedCommand",
            new_name="Skill",
        ),
        migrations.AlterField(
            model_name="skill",
            name="channel",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="skills",
                to="core.channel",
            ),
        ),
    ]
