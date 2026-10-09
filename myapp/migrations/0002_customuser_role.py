from django.db import migrations, models


def promote_existing_admins(apps, schema_editor):
    """Anyone who was already staff/superuser was shown as 'Administrator'
    in the sidebar, so keep them as administrators. Everyone else is Faculty."""
    CustomUser = apps.get_model("myapp", "CustomUser")
    CustomUser.objects.filter(models.Q(is_staff=True) | models.Q(is_superuser=True)).update(role="administrator")


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0001_initial"),
    ]

    operations = [
        migrations.AddField(
            model_name="customuser",
            name="role",
            field=models.CharField(
                choices=[("administrator", "Administrator"), ("faculty", "Faculty")],
                default="faculty",
                max_length=20,
            ),
        ),
        migrations.RunPython(promote_existing_admins, migrations.RunPython.noop),
    ]
