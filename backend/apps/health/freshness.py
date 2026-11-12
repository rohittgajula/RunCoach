"""R16 §C: dates on day metrics — the shared `Freshness` block and per-value dates.

`freshness_json(athlete)` is added to /today/, /briefing/today/, /insights/ and
/health/day/summary/; the rule itself is analysis/freshness.py.
"""

from __future__ import annotations

import datetime as dt

from django.utils import timezone

from analysis.freshness import RECENT_DAYS, assess, sync_verdict


def _local_now(athlete):
    """Seam for tests: the athlete's local now."""
    return athlete.local_now


def latest_dates(athlete, today: dt.date) -> dict:
    """{today_row, sleep, readiness}: the newest days (≤ today) that have them."""
    from apps.ingest.models import DailyMetrics

    rows = list(DailyMetrics.objects.filter(
        athlete=athlete, metric_date__lte=today,
        metric_date__gte=today - dt.timedelta(days=RECENT_DAYS + 1),
    ).order_by("-metric_date").only("metric_date", "sleep_seconds", "training_readiness"))
    sleep = next((r.metric_date for r in rows if r.sleep_seconds), None)
    readiness = next((r.metric_date for r in rows if r.training_readiness is not None), None)
    if sleep is None or readiness is None:
        older = DailyMetrics.objects.filter(athlete=athlete, metric_date__lte=today)
        if sleep is None:
            sleep = older.filter(sleep_seconds__gt=0).order_by("-metric_date") \
                .values_list("metric_date", flat=True).first()
        if readiness is None:
            readiness = older.filter(training_readiness__isnull=False) \
                .order_by("-metric_date").values_list("metric_date", flat=True).first()
    return {"sleep": sleep, "readiness": readiness}


def freshness_json(athlete) -> dict:
    now = _local_now(athlete)
    today = now.date()
    latest = latest_dates(athlete, today)
    verdict = assess(today=today, local_hour=now.hour,
                     has_sleep_today=latest["sleep"] == today,
                     has_readiness_today=latest["readiness"] == today,
                     latest_sleep_date=latest["sleep"],
                     latest_readiness_date=latest["readiness"])
    return {"as_of": timezone.now(), "today": today, **verdict,
            "latest_sleep_date": latest["sleep"],
            "latest_readiness_date": latest["readiness"],
            "last_sync_at": athlete.garmin_last_sync,
            # Whether the watch is still talking at all, which is a different
            # question from whether today's sleep has landed — and a louder one,
            # because every figure on the screen depends on the answer.
            "sync": sync_json(athlete, today, now)}


def reason_dates(athlete, today: dt.date, reasons: list[dict]) -> list[dict]:
    """/today/ reasons[] gain `date`: the day each value is from (planning.plan_services
    .snapshot_for — sleep/HRV/readiness only today's; resting HR and body battery today's,
    else yesterday's)."""
    from apps.ingest.models import DailyMetrics

    yesterday = today - dt.timedelta(days=1)
    rows = {r.metric_date: r for r in DailyMetrics.objects.filter(
        athlete=athlete, metric_date__in=[today, yesterday])}

    def recent(field):
        for day in (today, yesterday):
            row = rows.get(day)
            if row is not None and getattr(row, field, None):
                return day
        return None

    dates = {"sleep": today, "hrv": today, "readiness": today,
             "rhr": recent("resting_hr"), "body_battery": recent("body_battery_high"),
             "rpe": yesterday, "alcohol": yesterday}
    return [{**r, "date": dates.get(r.get("signal"), today)} for r in reasons]


def sync_json(athlete, today: dt.date, now) -> dict:
    """The Garmin-silence verdict, from stored fields only.

    No network probe: this rides on /today/, which is loaded on every visit, and
    a banner that costs a round trip to Garmin is a banner that makes the app
    slower for everybody to tell one person their watch is off.
    """
    from apps.activities.models import Activity

    last_activity = (
        Activity.objects.filter(athlete=athlete)
        .order_by("-local_date")
        .values_list("local_date", flat=True)
        .first()
    )
    return sync_verdict(
        today=today,
        connected=bool(athlete.garmin_connected),
        last_sync_at=athlete.garmin_last_sync,
        last_activity_date=last_activity,
        now=now,
    )
