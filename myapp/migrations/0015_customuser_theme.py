from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0014_learner_info"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="theme",
            field=models.CharField(blank=True, default="system", max_length=10),
        ),
    ]
