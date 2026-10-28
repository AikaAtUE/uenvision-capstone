from django.contrib.auth.hashers import check_password
from django.db import migrations, models

# The shared passwords used before temporary passwords existed (see models.OLD_SHARED_PASSWORDS).
OLD_SHARED_PASSWORDS = ("default123", "rizal123")


def flag_shared_passwords(apps, schema_editor):
    User = apps.get_model("myapp", "CustomUser")
    for user in User.objects.exclude(password="").only("pk", "password"):
        if any(check_password(p, user.password) for p in OLD_SHARED_PASSWORDS):
            User.objects.filter(pk=user.pk).update(must_change_password=True)


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0009_developer_role"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="must_change_password",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(flag_shared_passwords, migrations.RunPython.noop),
    ]
