from django.core.management import call_command
from django.db import migrations


def create_cache_table(apps, schema_editor):
    # The database cache (settings.CACHES) that holds failed-login counts; does nothing if it exists.
    call_command("createcachetable", database=schema_editor.connection.alias, verbosity=0)


class Migration(migrations.Migration):

    dependencies = [
        ("myapp", "0010_must_change_password"),
    ]

    operations = [
        migrations.RunPython(create_cache_table, migrations.RunPython.noop),
    ]
