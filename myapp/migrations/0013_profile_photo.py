import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0012_feedback_nudge"),
    ]

    operations = [
        migrations.CreateModel(
            name="ProfilePhoto",
            fields=[
                (
                    "user",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        primary_key=True,
                        related_name="profile_photo",
                        serialize=False,
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                ("data", models.BinaryField()),
                ("content_type", models.CharField(max_length=20)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddField(
            model_name="customuser",
            name="photo_updated",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
