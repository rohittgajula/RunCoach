"""Shared builders for the R10 tests."""

import datetime as dt

from django.utils import timezone

from apps.activities.models import Activity, ActivityMetrics, Segment
from apps.ingest.models import DailyMetrics


def run(athlete, day, *, km=4.0, cadence=150.0, gct=None, vo=None, stride=None, hr=140,
        pace=400.0, zones=None, drift=None, garmin_id=None, longest_s=600.0, easy=False):
    activity = Activity.objects.create(
        athlete=athlete, source="garmin_sync", sport="running", garmin_activity_id=garmin_id,
        started_at=timezone.make_aware(dt.datetime.combine(day, dt.time(7, 0))),
        local_date=day, total_timer_s=1800, total_distance_m=km * 1000, avg_hr=hr, max_hr=hr + 20)
    ActivityMetrics.objects.create(
        activity=activity, run_distance_m=km * 900, walk_distance_m=km * 100, run_fraction=0.9,
        run_duration_s=1600, walk_duration_s=200, stop_duration_s=0, run_block_count=1,
        longest_run_m=km * 500, longest_run_s=longest_s, custom_load=50, algorithm_version=1,
        time_in_zone=zones or {}, avg_run_cadence_spm=cadence, run_pace_s_per_km=pace,
        avg_run_hr=hr, avg_ground_contact_ms=gct, avg_vertical_oscillation_cm=vo,
        avg_stride_length_m=stride, hr_drift_percent=drift)
    if easy:
        # One run block at the athlete's easy pace, so "HR at easy pace" has a value.
        Segment.objects.create(activity=activity, index=0, kind="run", start_offset_s=0,
                               duration_s=1600, distance_m=km * 900,
                               avg_pace_s_per_km=athlete.easy_pace_min + 10, hr_avg=hr)
    return activity


def night(athlete, day, *, hours=7.0, need_h=8.0, bed=(23, 0), wake=None, **fields):
    start = dt.datetime.combine(day - dt.timedelta(days=1), dt.time(*bed)) if bed[0] >= 12 \
        else dt.datetime.combine(day, dt.time(*bed))
    end = start + dt.timedelta(hours=hours)
    if wake:
        end = dt.datetime.combine(day, dt.time(*wake))
    # Stored like the ingest does: local wall-clock time in a UTC-aware field.
    start, end = start.replace(tzinfo=dt.timezone.utc), end.replace(tzinfo=dt.timezone.utc)
    defaults = {"sleep_seconds": round(hours * 3600), "sleep_need_seconds": round(need_h * 3600),
                "sleep_start_local": start, "sleep_end_local": end, **fields}
    row, _ = DailyMetrics.objects.update_or_create(athlete=athlete, metric_date=day,
                                                   defaults=defaults)
    return row


def metric(athlete, day, **fields):
    row, _ = DailyMetrics.objects.update_or_create(athlete=athlete, metric_date=day,
                                                   defaults=fields)
    return row
