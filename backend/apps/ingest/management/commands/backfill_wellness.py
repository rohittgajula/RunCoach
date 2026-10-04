"""Re-map stored wellness payloads onto new DailyMetrics columns. No Garmin calls."""

from django.core.management.base import BaseCommand

from apps.athletes.models import Athlete
from apps.ingest.garmin_wellness import backfill_from_raw


class Command(BaseCommand):
    help = "Fill new DailyMetrics columns from each row's stored raw payloads."

    def add_arguments(self, parser):
        parser.add_argument("--athlete", type=int)

    def handle(self, *args, **options):
        athlete = Athlete.objects.get(pk=options["athlete"]) if options["athlete"] else None
        updated = backfill_from_raw(athlete)
        self.stdout.write(self.style.SUCCESS(f"{updated} day(s) updated"))
