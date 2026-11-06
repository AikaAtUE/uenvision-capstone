"""python manage.py rebuild_subject_profiles

Rebuilds the subject profiles (subject_profiles.py) from the curriculum survey answers.
They rebuild by themselves after every survey; this is for after a deploy or an import.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Rebuild which skills each subject builds up, from the curriculum survey answers."

    def handle(self, *args, **options):
        from ... import subject_profiles
        real = subject_profiles.rebuild(False)
        dummy = subject_profiles.rebuild(True)
        self.stdout.write(f"Subject profiles rebuilt: {real} subject skills (real answers), {dummy} (dummy answers).")
