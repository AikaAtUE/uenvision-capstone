from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0020_context_recommendations"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="tours_seen",
            field=models.JSONField(blank=True, default=list),
        ),
    ]
