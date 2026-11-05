from django.db import migrations


def approve_non_faculty(apps, schema_editor):
    """Only faculty sign-ups wait for approval. Accounts of any other role that were still
    marked "not approved yet" (e.g. a faculty sign-up whose role was later changed) are
    approved, so the Accounts notice only counts real faculty sign-ups."""
    User = apps.get_model("myapp", "CustomUser")
    User.objects.filter(is_approved=False).exclude(role="faculty").update(is_approved=True)


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0017_lowercase_emails"),
    ]

    operations = [
        migrations.RunPython(approve_non_faculty, migrations.RunPython.noop),
    ]
