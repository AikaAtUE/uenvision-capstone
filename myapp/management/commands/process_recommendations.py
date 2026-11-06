"""python manage.py process_recommendations [--max N]

Works through the recommendations queue right away (rec_queue.py): the skills that
surveys queued for Gemini to find learning resources for. run_automation does this too,
every 5 minutes on the server; this is for a laptop, where no timer runs.
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Find learning resources for the skills waiting in the recommendations queue."

    def add_arguments(self, parser):
        parser.add_argument("--max", type=int, default=30, help="At most this many skills (default 30).")

    def handle(self, *args, **options):
        from ... import rec_queue
        self.stdout.write(rec_queue.process(max_jobs=options["max"]))
