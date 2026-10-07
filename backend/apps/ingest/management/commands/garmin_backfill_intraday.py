"""R11 §A backfill: the last 30 days of intraday heart rate, stress + Body Battery and
steps (3 requests per day).

    python manage.py garmin_backfill_intraday --athlete 3            # queue on the garmin queue
    python manage.py garmin_backfill_intraday --all [--days 30]
    python manage.py garmin_backfill_intraday --athlete 3 --now      # run here, in this process
    python manage.py garmin_backfill_intraday --athlete 3 --force    # re-fetch complete days too

Work is queued in chunks of 7 days, 5 minutes apart, athletes one after another, so the
whole backfill never arrives as one burst from this IP. Inside a chunk the calls are
GARMIN_SLOW_PAUSE_S apart and the first 429 stops it (the breaker then holds every
Garmin task). Refuses to start while the breaker is open. Days already stored as
complete are skipped.
"""

from django.core.management.base import BaseCommand, CommandError

from apps.athletes.models import Athlete
from apps.ingest.garmin_intraday import backfill_days
from apps.ingest.tasks import BACKFILL_CHUNK_DAYS, backfill_intraday, garmin_blocked

CHUNK_SPACING_S = 300


class Command(BaseCommand):
    help = "Backfill R11 intraday Garmin data (HR, stress, Body Battery, steps)."

    def add_arguments(self, parser):
        parser.add_argument("--athlete", type=int, help="One athlete id.")
        parser.add_argument("--all", action="store_true", help="Every connected athlete.")
        parser.add_argument("--days", type=int, default=30)
        parser.add_argument("--now", action="store_true",
                            help="Run in this process instead of queueing.")
        parser.add_argument("--force", action="store_true",
                            help="Also re-fetch days already stored as complete.")

    def handle(self, *args, **options):
        if garmin_blocked():
            raise CommandError("The Garmin circuit breaker is open; try again later.")
        days = max(1, min(options["days"], 90))
        athletes = Athlete.objects.filter(garmin_connected=True)
        if options["athlete"]:
            athletes = athletes.filter(pk=options["athlete"])
        elif not options["all"]:
            raise CommandError("Pass --athlete ID or --all.")
        found = list(athletes)
        if not found:
            raise CommandError("No connected athlete matched.")
        slot = 0
        for athlete in found:
            wanted = backfill_days(athlete, days, force=options["force"])
            if not wanted:
                self.stdout.write(f"athlete {athlete.pk}: nothing to fetch")
                continue
            chunks = [wanted[i:i + BACKFILL_CHUNK_DAYS]
                      for i in range(0, len(wanted), BACKFILL_CHUNK_DAYS)]
            for chunk in chunks:
                isos = [d.isoformat() for d in chunk]
                if options["now"]:
                    result = backfill_intraday(athlete.pk, isos)
                    self.stdout.write(f"athlete {athlete.pk} {isos[-1]}…{isos[0]}: {result}")
                    if result.get("skipped") == "rate_limited" or result.get("rate_limited"):
                        self.stdout.write("Rate limited — stopping.")
                        return
                else:
                    backfill_intraday.apply_async((athlete.pk, isos),
                                                  countdown=slot * CHUNK_SPACING_S)
                    slot += 1
            if not options["now"]:
                self.stdout.write(f"athlete {athlete.pk}: {len(wanted)} days queued "
                                  f"in {len(chunks)} chunks")
