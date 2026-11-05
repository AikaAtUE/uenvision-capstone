from django.db import migrations


def lowercase_emails(apps, schema_editor):
    """Emails are no longer case-sensitive: save the existing ones in lowercase. Two accounts
    whose emails differ only by case are left as they are (an administrator removes one),
    since lowercasing both would break the "one account per email" rule."""
    User = apps.get_model("myapp", "CustomUser")
    rows = list(User.objects.values_list("pk", "email"))
    taken = {}
    for pk, email in rows:
        taken.setdefault((email or "").strip().lower(), []).append(pk)
    for pk, email in rows:
        low = (email or "").strip().lower()
        if email != low and len(taken[low]) == 1:
            User.objects.filter(pk=pk).update(email=low)


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0016_theme_default_light"),
    ]

    operations = [
        migrations.RunPython(lowercase_emails, migrations.RunPython.noop),
    ]
