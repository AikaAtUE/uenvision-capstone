from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0005_learner_roles_and_survey_user"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="email_verified",
            field=models.BooleanField(default=True),
        ),
    ]
