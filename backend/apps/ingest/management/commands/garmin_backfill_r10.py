"""R10 §B history backfill: the last 180 days of endurance score, fitness age, lactate
threshold, body composition, plus PRs and gear; stored sleep / training-status payloads
are re-read for the new columns without any request.

    python manage.py garmin_backfill_r10 --athlete 3            # queue on the garmin queue
    python manage.py garmin_backfill_r10 --athlete 3 --now      # run here, in this process
    python manage.py garmin_backfill_r10 --all [--days 90]

Athletes are queued 10 minutes apart; each run pauses between calls and stops at the
first 429 (the circuit breaker then holds every Garmin task for 45 minutes).
"""

from django.core.management.base import BaseCommand, CommandError

from apps.athletes.models import Athlete
from apps.ingest.tasks import backfill_r10, garmin_blocked

SPACING_S = 600


class Command(BaseCommand):
    help = "Backfill R10 Garmin data (endurance, fitness age, LT, body, PRs, gear)."

    def add_arguments(self, parser):
        parser.add_argument("--athlete", type=int, help="One athlete id.")
        parser.add_argument("--all", action="store_true", help="Every connected athlete.")
        parser.add_argument("--days", type=int, default=180)
        parser.add_argument("--now", action="store_true",
                            help="Run in this process instead of queueing.")

    def handle(self, *args, **options):
        if garmin_blocked():
            raise CommandError("The Garmin circuit breaker is open; try again later.")
        days = max(7, min(options["days"], 365))
        athletes = Athlete.objects.filter(garmin_connected=True)
        if options["athlete"]:
            athletes = athletes.filter(pk=options["athlete"])
        elif not options["all"]:
            raise CommandError("Pass --athlete ID or --all.")
        ids = list(athletes.values_list("pk", flat=True))
        if not ids:
            raise CommandError("No connected athlete matched.")
        for index, athlete_id in enumerate(ids):
            if options["now"]:
                result = backfill_r10(athlete_id, days)
                self.stdout.write(f"athlete {athlete_id}: {result}")
                if result.get("skipped") == "rate_limited" or result.get("rate_limited"):
                    self.stdout.write("Rate limited — stopping.")
                    break
            else:
                backfill_r10.apply_async((athlete_id, days), countdown=index * SPACING_S)
                self.stdout.write(f"athlete {athlete_id}: queued")
