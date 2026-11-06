"""python manage.py ghost_job_check

The last step of a Data Extraction run: checks the extracted job postings for possible
ghost jobs with the saved Ghost Job Detection settings and prints how many are marked.
Postings are only marked (see ghost_jobs.py); nothing is removed from any file."""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Check the extracted job postings for possible ghost jobs and report how many are marked."

    def handle(self, *args, **options):
        from ... import ghost_jobs
        from ...pipeline import manager as pipeline

        pipeline.ensure_skill_csvs()
        ghost_jobs._CACHE.update(key=None, value=None)
        found = ghost_jobs.detect()
        if found is None:
            self.stdout.write("No extracted skills yet, so there are no postings to check.")
            return
        cfg = ghost_jobs.get_settings()
        flagged = [info for info in found.values() if info["flagged"]]
        excluded = sum(1 for info in flagged if not info["keep_when_excluding"])
        self.stdout.write(f"Checked {len(found)} posting(s) with these settings: "
                          f"same job posted twice {'on' if cfg['flag_duplicates'] else 'off'}, "
                          f"salary hidden {'on' if cfg['flag_hidden_salary'] else 'off'}, "
                          f"company not verified {'on' if cfg['flag_unverified'] else 'off'}, "
                          f"description shorter than {cfg['min_description_chars']} characters, "
                          f"{cfg['weak_signs_needed']} weak sign(s) needed.")
        self.stdout.write(f"{len(flagged)} posting(s) marked as possible ghost jobs; "
                          f"{excluded} of them are left out when \"Exclude possible ghost jobs\" is on.")
