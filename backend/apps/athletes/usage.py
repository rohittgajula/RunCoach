"""R26 §3: which screens actually get opened.

    POST /usage/           a batch of screen opens
    GET  /usage/summary/   counts over the last N days

The point is subtraction. The app has grown thirteen pages, five tabs, around
sixty component folders and sixteen optional Today cards, and nobody — not the
person using it and not the person building it — knows which of those are ever
opened. Deleting on a hunch removes something that was being used; keeping
everything is how a tool becomes tiring. This endpoint is the evidence, and it is
worth having for a fortnight and then acting on.

Three constraints shape it:

* **It must never cost anything.** It is written on navigation, which is the moment
  the app must feel fastest. So the client batches and fires and forgets, and
  nothing here does more than one insert and one delete.
* **It must not be able to say more than it claims.** Keys only, from a fixed
  charset. No screen contents, no text he typed, no URLs with ids in them.
* **It must not grow forever.** A table written to on every navigation would end up
  the biggest one in the database, to answer a question that is only ever about the
  last few weeks.

The catalogue of what *could* be opened lives in the frontend, which already has
it (`todayLayout.ts`, the Health section list, the tab list). So "never opened once"
is worked out there by subtracting these counts from that list, rather than by
keeping a second copy of the catalogue in Python that would drift from the first.
"""

from __future__ import annotations

import datetime as dt
import re

from django.db.models import Count, Max
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import ScreenView

#: Keys are identifiers from the source, not free text. Anything else is dropped.
#: A leading `/` is allowed because route keys are paths ("/health/day"); a leading
#: dot is not, so no key can be a traversal.
KEY_RE = re.compile(r"^[a-z0-9/][a-z0-9_/:-]{0,63}$")
#: One request carries at most this many. The client batches every 20 seconds, so
#: hitting this means something is looping, and the rest is not worth storing.
MAX_BATCH = 60
#: Per athlete per day. A navigation loop or a stuck effect must not be able to
#: write unboundedly, and nobody opens 2000 screens in a day on purpose.
MAX_PER_DAY = 2000
#: How far back a client may claim an event happened. Covers a phone that was
#: offline for a while; beyond it the timestamp is not trustworthy enough to chart.
MAX_BACKDATE = dt.timedelta(days=3)
#: Rows older than this are deleted on write.
RETAIN_DAYS = 120
#: The default window the summary covers.
DEFAULT_DAYS = 14
MAX_DAYS = 90


class EventIn(serializers.Serializer):
    key = serializers.CharField(max_length=64)
    kind = serializers.ChoiceField(choices=[k.value for k in ScreenView.Kind])
    at = serializers.DateTimeField(required=False, allow_null=True)

    def validate_key(self, value: str) -> str:
        value = value.strip().lower()
        if not KEY_RE.match(value):
            raise serializers.ValidationError("not an identifier")
        return value


class BatchIn(serializers.Serializer):
    events = EventIn(many=True)

    def validate_events(self, value):
        if len(value) > MAX_BATCH:
            # Truncate rather than refuse: losing the tail of a runaway batch is
            # fine, and a 400 would make the client retry it forever.
            return value[:MAX_BATCH]
        return value


@api_view(["POST"])
@permission_classes([IsAuthenticated])
def record(request):
    athlete = request.user.athlete
    form = BatchIn(data=request.data)
    form.is_valid(raise_exception=True)
    events = form.validated_data["events"]

    now = timezone.now()
    today = athlete.local_today
    already = ScreenView.objects.filter(athlete=athlete, local_date=today).count()
    room = max(0, MAX_PER_DAY - already)
    if room <= 0:
        return Response({"stored": 0, "reason": "daily cap"}, status=status.HTTP_202_ACCEPTED)

    rows = []
    for event in events[:room]:
        at = event.get("at") or now
        # A timestamp from the future, or from before the app existed, is a broken
        # clock. Keep the event, fix the time — the key is the part that matters.
        if at > now + dt.timedelta(minutes=5) or at < now - MAX_BACKDATE:
            at = now
        rows.append(ScreenView(
            athlete=athlete, key=event["key"], kind=event["kind"], at=at,
            local_date=_local_date(athlete, at),
        ))
    ScreenView.objects.bulk_create(rows)

    ScreenView.objects.filter(
        athlete=athlete, local_date__lt=today - dt.timedelta(days=RETAIN_DAYS)
    ).delete()
    return Response({"stored": len(rows)}, status=status.HTTP_202_ACCEPTED)


def _local_date(athlete, at: dt.datetime) -> dt.date:
    from zoneinfo import ZoneInfo

    try:
        zone = ZoneInfo(athlete.timezone or "UTC")
    except Exception:  # noqa: BLE001 — a bad zone must not lose the event
        zone = ZoneInfo("UTC")
    return at.astimezone(zone).date()


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def summary(request):
    """Counts per key over the window, most-opened first.

    `days_seen` matters more than `views` for the decision this feeds: a screen
    opened forty times in one sitting and never again is a screen he bounced off,
    and one opened once a day for a fortnight is part of how he uses the app.
    """
    athlete = request.user.athlete
    try:
        days = min(max(int(request.query_params.get("days", DEFAULT_DAYS)), 1), MAX_DAYS)
    except (TypeError, ValueError):
        days = DEFAULT_DAYS

    today = athlete.local_today
    start = today - dt.timedelta(days=days - 1)
    rows = (ScreenView.objects
            .filter(athlete=athlete, local_date__gte=start, local_date__lte=today)
            .values("key", "kind")
            .annotate(views=Count("id"), days_seen=Count("local_date", distinct=True),
                      last_seen=Max("local_date"))
            .order_by("-days_seen", "-views"))
    out = list(rows)
    return Response({
        "days": days, "from": start, "to": today,
        "total_views": sum(r["views"] for r in out),
        "keys": len(out),
        "rows": out,
        "retain_days": RETAIN_DAYS,
        "note": (
            "Only which screens were opened, and when. Never what was on them, what "
            f"you typed, or where you were. Kept for {RETAIN_DAYS} days, then deleted."
        ),
    })
