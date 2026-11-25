"""Deriving segments and metrics from stored per-second records.

The Django-facing half of the metrics engine. Everything numerical happens in
`analysis`, which imports no Django; this module only loads rows, calls it, and
stores the result.
"""

from __future__ import annotations

import logging

from django.db import transaction

from analysis import dynamics, heart_rate, load, zones as zone_maths
from analysis.running_truth import summarise
from analysis.segmentation import (
    ALGORITHM_VERSION, NotSegmentable, Sample, check_segmentable, segment_samples,
)

from .models import Activity, ActivityMetrics, Segment

logger = logging.getLogger(__name__)


def load_samples(activity: Activity) -> list[Sample]:
    """R17: the series the run's data-quality `use` picks (raw, or the cleaned copy)."""
    from .quality import series

    rows = series(activity, ("distance_m", "speed_mps", "cadence_spm", "heart_rate"))
    return [Sample(**row) for row in rows]


def _dynamics(activity: Activity, segments) -> dict:
    from .quality import series

    rows = series(activity, (
        "cadence_spm", "stride_length_m", "vertical_oscillation_mm",
        "ground_contact_ms", "respiration_rate", "speed_mps",
    ))
    windows = [(s.start_offset_s, s.duration_s) for s in segments if s.kind == "run"]
    return dynamics.summarise([dynamics.DynamicsSample(**row) for row in rows], windows)


def _training_effect(activity: Activity) -> dict:
    """From the stored FIT session message. A missing or unreadable file is a gap."""
    empty = {"training_effect_aerobic": None, "training_effect_anaerobic": None,
             "gct_balance_left_pct": None}
    raw = activity.raw_file
    if raw is None or not raw.file:
        return empty
    try:
        from apps.ingest.fit_parser import training_effect

        with raw.file.open("rb") as handle:
            values = training_effect(handle)
    except Exception:  # noqa: BLE001 — a derived extra must not fail derivation
        logger.warning("could not read training effect for activity %s", activity.pk)
        return empty
    out = {k: (round(float(v), 1) if v is not None else None) for k, v in values.items()}
    balance = out.get("gct_balance_left_pct")
    # A balance outside 30–70 % is a sensor artefact, not a gait.
    if balance is not None and not 30 <= balance <= 70:
        out["gct_balance_left_pct"] = None
    out.setdefault("gct_balance_left_pct", None)
    return out


@transaction.atomic
def derive(activity: Activity, reassess: bool = True) -> ActivityMetrics | None:
    """Segment an activity and store its metrics. Idempotent — safe to re-run.

    Returns None when the activity cannot be honestly segmented (a cycling session,
    a strength session, anything without a cadence sensor). That is a legitimate
    outcome, not a failure: better no number than a confident wrong one.
    """
    if reassess:
        # R17 §2: the bad-data filter first — its `use` decides which series follows.
        from .quality import assess

        activity.quality = assess(activity)
    samples = load_samples(activity)

    try:
        check_segmentable(activity.sport, samples)
    except NotSegmentable as reason:
        logger.info("activity %s not segmentable: %s", activity.pk, reason)
        activity.segments.all().delete()
        ActivityMetrics.objects.filter(activity=activity).delete()
        # Still stamp the version: this activity HAS been considered under this
        # algorithm and deliberately left unsegmented, which is different from
        # never having been looked at.
        activity.segmentation_version = ALGORITHM_VERSION
        activity.save(update_fields=["segmentation_version"])
        return None

    athlete = activity.athlete
    threshold = athlete.run_cadence_threshold
    segments = segment_samples(samples, run_cadence_threshold=threshold)
    truth = summarise(segments)

    # Delete-and-recreate rather than update: a partial rewrite would leave stale
    # segments from a previous algorithm version interleaved with new ones.
    activity.segments.all().delete()
    Segment.objects.bulk_create(
        Segment(
            activity=activity,
            index=s.index,
            kind=s.kind,
            start_offset_s=s.start_offset_s,
            duration_s=s.duration_s,
            distance_m=s.distance_m,
            avg_pace_s_per_km=s.avg_pace_s_per_km,
            avg_cadence_spm=s.avg_cadence_spm,
            hr_start=s.hr_start,
            hr_end=s.hr_end,
            hr_avg=s.hr_avg,
            hr_max=s.hr_max,
            hr_recovery_60s=s.hr_recovery_60s,
            hr_overshoot_bpm=s.hr_overshoot_bpm,
        )
        for s in segments
    )

    athlete_zones = athlete.zones()
    in_zone = (
        zone_maths.time_in_zones(
            ((s.offset_s, s.heart_rate) for s in samples), athlete_zones
        )
        if athlete_zones
        else {}
    )

    metrics, _ = ActivityMetrics.objects.update_or_create(
        activity=activity,
        defaults={
            "time_in_zone": in_zone,
            "run_distance_m": truth.run_distance_m,
            "walk_distance_m": truth.walk_distance_m,
            "run_fraction": truth.run_fraction,
            "run_duration_s": truth.run_duration_s,
            "walk_duration_s": truth.walk_duration_s,
            "stop_duration_s": truth.stop_duration_s,
            "run_block_count": truth.run_block_count,
            "longest_run_m": truth.longest_run_m,
            "longest_run_s": truth.longest_run_s,
            "run_pace_s_per_km": truth.run_pace_s_per_km,
            "walk_pace_s_per_km": truth.walk_pace_s_per_km,
            "blended_pace_s_per_km": truth.blended_pace_s_per_km,
            "avg_run_cadence_spm": truth.avg_run_cadence_spm,
            "avg_run_hr": truth.avg_run_hr,
            # Segments, not raw samples: drift over the whole session measures
            # the run/walk mix rather than the heart. See heart_rate.py.
            "hr_drift_percent": heart_rate.hr_drift_percent(samples, segments),
            "custom_load": load.session_load(
                truth.run_duration_s / 60, truth.walk_duration_s / 60
            ),
            "load_formula_version": load.LOAD_FORMULA_VERSION,
            **_dynamics(activity, segments),
            **_training_effect(activity),
            "algorithm_version": ALGORITHM_VERSION,
        },
    )

    activity.segmentation_version = ALGORITHM_VERSION
    activity.save(update_fields=["segmentation_version"])

    logger.info("derived activity %s: %s", activity.pk, truth)
    return metrics
