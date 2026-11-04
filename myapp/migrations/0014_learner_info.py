from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0013_profile_photo"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="learner_info",
            field=models.JSONField(blank=True, default=dict),
        ),
    ]
