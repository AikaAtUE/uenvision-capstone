"""python manage.py run_automation [--now] [--no-wait]

Checks the Automation schedule (Data -> Data Extraction -> Automation) and, when a run is
due, runs the whole Data Extraction pipeline with the multiple search list. On the server,
deploy/uenvision-automation.timer runs this every 5 minutes.

Each check also works through the recommendations queue first (rec_queue.py): the skills
that surveys queued for Gemini to find learning resources for.

--now      start an automatic run right away (even if Automation is off), e.g. to test it
--no-wait  return as soon as the run has started instead of staying until it ends
"""
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Start the scheduled Data Extraction run when it is due (run every few minutes by a timer)."

    def add_arguments(self, parser):
        parser.add_argument("--now", action="store_true", help="Start an automatic run right away.")
        parser.add_argument("--no-wait", action="store_true", help="Don't wait for the run to end.")

    def handle(self, *args, **options):
        from ... import automation, rec_queue
        try:
            self.stdout.write(rec_queue.process())
        except Exception as exc:   # the data extraction schedule must still be checked
            self.stderr.write(f"Recommendations queue: {exc}")
        self.stdout.write(automation.tick(force=options["now"], wait=not options["no_wait"]))
