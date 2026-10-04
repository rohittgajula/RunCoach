"""Shared builders for the R6 tests."""

import datetime as dt

from django.utils import timezone

from apps.activities.models import Activity, ActivityMetrics, Segment


def make_activity(athlete, day, *, sport="running", minutes=30, run_s=1500, walk_s=300,
                  longest_s=480, load=55, zones=None, blocks=None, cadence=150,
                  garmin_id=None):
    activity = Activity.objects.create(
        athlete=athlete, source="garmin_sync", sport=sport, garmin_activity_id=garmin_id,
        started_at=timezone.make_aware(dt.datetime.combine(day, dt.time(7, 0))),
        local_date=day, total_timer_s=minutes * 60, total_distance_m=4000, calories=300,
        avg_hr=140, max_hr=160,
    )
    ActivityMetrics.objects.create(
        activity=activity, run_distance_m=run_s / 0.4, walk_distance_m=walk_s / 0.8,
        run_fraction=run_s / max(run_s + walk_s, 1), run_duration_s=run_s,
        walk_duration_s=walk_s, stop_duration_s=0, run_block_count=1 if run_s else 0,
        longest_run_m=longest_s / 0.4, longest_run_s=longest_s, custom_load=load,
        algorithm_version=1, time_in_zone=zones or {}, avg_run_cadence_spm=cadence,
        run_pace_s_per_km=400, walk_pace_s_per_km=750,
    )
    offset = 0.0
    for index, block in enumerate(blocks or []):
        Segment.objects.create(
            activity=activity, index=index, kind=block.get("kind", "run"),
            start_offset_s=offset, duration_s=block["duration_s"],
            distance_m=block["duration_s"] * 2.5, avg_pace_s_per_km=block.get("pace", 400),
            hr_avg=block.get("hr_avg"), hr_max=block.get("hr_max"),
        )
        offset += block["duration_s"]
    return activity
