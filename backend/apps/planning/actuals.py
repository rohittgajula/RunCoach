"""What was actually done, next to what was planned (R6 §3).

`actual_json` is the block shown under a completed workout and on an unplanned run;
`compliance_json` scores it against the prescription with analysis/compliance.py;
`review_json` is the stored AI interpretation, if one has been generated.
"""

from __future__ import annotations

from analysis.compliance import ZONES, evaluate, time_above
from apps.activities.models import Activity


def _run_blocks(activity: Activity) -> list[dict]:
    return [
        {"duration_s": s.duration_s, "hr_avg": s.hr_avg, "hr_max": s.hr_max,
         "pace_s_per_km": s.avg_pace_s_per_km}
        for s in activity.segments.all() if s.kind == "run"
    ]


def _round(value, digits=0):
    if value is None:
        return None
    return round(value) if digits == 0 else round(value, digits)


def actual_json(activity: Activity) -> dict:
    from .presenters import _activity_steps

    metrics = getattr(activity, "metrics", None)
    zones = (metrics.time_in_zone or {}) if metrics else {}
    return {
        "activity_id": activity.pk,
        "duration_s": round(activity.total_timer_s or activity.total_elapsed_s or 0),
        "distance_m": round(activity.total_distance_m or 0),
        "run_distance_m": _round(metrics.run_distance_m) if metrics else None,
        "walk_distance_m": _round(metrics.walk_distance_m) if metrics else None,
        "run_fraction": _round(metrics.run_fraction, 2) if metrics else None,
        "longest_run_s": _round(metrics.longest_run_s) if metrics else None,
        "avg_hr": activity.avg_hr,
        "max_hr": activity.max_hr,
        "avg_cadence_spm": _round(metrics.avg_run_cadence_spm) if metrics
        else _round(activity.avg_cadence_spm),
        "avg_pace_s_per_km": _round(metrics.run_pace_s_per_km) if metrics else None,
        # Z1..Z5 only; seconds below Z1 are left out (spec shape).
        "time_in_zone": {z: zones.get(z, 0) for z in ZONES} if zones else None,
        "steps": _activity_steps(activity),
        # R6 §6 extras: running dynamics and Garmin's training effect.
        "max_cadence_spm": _round(metrics.max_run_cadence_spm) if metrics else None,
        "avg_stride_length_m": metrics.avg_stride_length_m if metrics else None,
        "avg_vertical_oscillation_cm": metrics.avg_vertical_oscillation_cm if metrics else None,
        "avg_ground_contact_ms": metrics.avg_ground_contact_ms if metrics else None,
        "avg_respiration": metrics.avg_respiration if metrics else None,
        "training_effect_aerobic": metrics.training_effect_aerobic if metrics else None,
        "training_effect_anaerobic": metrics.training_effect_anaerobic if metrics else None,
        **_above_cap(activity),
    }


def _above_cap(activity: Activity) -> dict:
    """R7 §3: time over the easy-day guard's HR cap (Z2 top, else the HR ceiling).

    Runs only; null without HR samples. Percent is of the time with HR recorded.
    """
    from .presenters import guard_base, is_run

    empty = {"time_above_cap_s": None, "time_above_cap_pct": None, "hr_cap": None}
    if not is_run(activity):
        return empty
    base = guard_base(activity.athlete)
    cap = base["z2_high"] or base["hr_ceiling"]
    samples = activity.records.values_list("offset_s", "heart_rate")
    result = time_above(samples, cap)
    if result is None:
        return empty
    above, total = result
    return {"time_above_cap_s": above, "time_above_cap_pct": round(above / total * 100),
            "hr_cap": cap}


def checkin_rpe(activity: Activity) -> int | None:
    """The post-run check-in's RPE for this activity (R7 §2), if any."""
    from apps.journal.models import JournalEntry

    values = list(JournalEntry.objects.filter(
        athlete_id=activity.athlete_id, activity=activity, rpe__isnull=False,
    ).values_list("rpe", flat=True))
    return max(values) if values else None


def compliance_inputs(workout, activity: Activity) -> tuple[dict, dict]:
    metrics = getattr(activity, "metrics", None)
    planned = {"kind": workout.kind, "duration_s": workout.duration_s,
               "target_zone": workout.target_zone, "steps": workout.steps or []}
    actual = {
        "duration_s": activity.total_timer_s or activity.total_elapsed_s or 0,
        "run_duration_s": metrics.run_duration_s if metrics else 0,
        "longest_run_s": metrics.longest_run_s if metrics else 0,
        "time_in_zone": (metrics.time_in_zone or None) if metrics else None,
        "run_blocks": _run_blocks(activity),
        "rpe": checkin_rpe(activity),
    }
    return planned, actual


def compliance_json(workout, activity: Activity) -> dict:
    planned, actual = compliance_inputs(workout, activity)
    return evaluate(planned, actual, workout.athlete.hr_ceiling)


def review_json(activity: Activity | None) -> dict:
    """The newest stored review for this activity, or status "none"."""
    from apps.coaching.models import AIAnalysis

    empty = {"status": "none", "summary_md": "", "went_well": [], "to_improve": [],
             "generated_at": None}
    if activity is None:
        return empty
    row = (AIAnalysis.objects.filter(athlete_id=activity.athlete_id, activity=activity,
                                     kind=AIAnalysis.Kind.REVIEW)
           .order_by("-created_at").first())
    if row is None:
        return empty
    result = row.result or {}
    return {"status": "ready", "summary_md": result.get("summary_md", ""),
            "went_well": result.get("went_well", []),
            "to_improve": result.get("to_improve", []), "generated_at": row.created_at}
