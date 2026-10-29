from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0011_cache_table"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="app_uses",
            field=models.PositiveIntegerField(default=0),
        ),
        migrations.AddField(
            model_name="customuser",
            name="feedback_snoozed_until",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
