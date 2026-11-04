from django.db import migrations, models


def system_to_light(apps, schema_editor):
    # Accounts got "system" from 0015 before anyone could choose; light is the default now.
    apps.get_model("myapp", "CustomUser").objects.filter(theme__in=["system", ""]).update(theme="light")


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0015_customuser_theme"),
    ]

    operations = [
        migrations.AlterField(
            model_name="customuser",
            name="theme",
            field=models.CharField(blank=True, default="light", max_length=10),
        ),
        migrations.RunPython(system_to_light, migrations.RunPython.noop),
    ]
