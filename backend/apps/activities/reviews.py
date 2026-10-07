"""R13 §7: the post-run coach review (Django half; maths in analysis/run_review.py).

Built after each run is segmented (planning.after_run) and refreshed when its post-run
check-in is saved. Deterministic bullets; the optional AI paragraph gets aggregates only
(the comparison rows and bullets — no per-second data, no notes).
"""

from __future__ import annotations

import datetime as dt
import json
import logging

from django.utils import timezone

from analysis import run_review as maths

from .models import Activity, RunReview

logger = logging.getLogger(__name__)

HISTORY_DAYS = 120
RECENT_HOURS = 24


def _point(activity: Activity, kind: str) -> maths.RunPoint:
    m = getattr(activity, "metrics", None)
    return maths.RunPoint(
        activity_id=activity.pk, date=activity.local_date, kind=kind,
        km=(activity.total_distance_m or 0) / 1000,
        pace=m.run_pace_s_per_km if m else None,
        hr=(m.avg_run_hr or activity.avg_hr) if m else activity.avg_hr,
        drift=m.hr_drift_percent if m else None,
        cadence=m.avg_run_cadence_spm if m else None,
        run_fraction=m.run_fraction if m else None)


def _kinds(athlete, activity_ids) -> dict[int, str]:
    from apps.planning.models import PlannedWorkout

    return dict(PlannedWorkout.objects.filter(athlete=athlete,
                                              completed_activity_id__in=list(activity_ids))
                .values_list("completed_activity_id", "kind"))


def compute(activity: Activity) -> dict:
    """The review payload (no AI). `available: false` for non-runs."""
    from apps.planning.actuals import checkin_rpe
    from apps.planning.auto_adjust import _run_s, _zone_top
    from apps.planning.models import PlannedWorkout

    base = {"activity_id": activity.pk, "date": activity.local_date.isoformat()}
    if "run" not in (activity.sport or "").lower():
        return {**base, "available": False, "reason": "not_a_run", "kind": None,
                "bucket": None, "compared_with": 0, "metrics": [], "went_well": [],
                "to_improve": [], "next_time": []}
    metrics = getattr(activity, "metrics", None)
    if metrics is None:
        return {**base, "available": False, "reason": "no_metrics", "kind": None,
                "bucket": None, "compared_with": 0, "metrics": [], "went_well": [],
                "to_improve": [], "next_time": []}
    athlete = activity.athlete
    history = list(Activity.objects.filter(
        athlete=athlete, sport__icontains="run",
        local_date__gte=activity.local_date - dt.timedelta(days=HISTORY_DAYS),
        local_date__lte=activity.local_date).select_related("metrics"))
    kinds = _kinds(athlete, [a.pk for a in history] + [activity.pk])
    points = [_point(a, kinds.get(a.pk, "EASY")) for a in history
              if getattr(a, "metrics", None) is not None]
    run = _point(activity, kinds.get(activity.pk, "EASY"))
    workout = PlannedWorkout.objects.filter(athlete=athlete, completed_activity=activity).first()
    completion = None
    if workout is not None:
        planned = _run_s(workout.original_steps if workout.adjusted_by == "checkin"
                         and workout.original_steps else workout.steps)
        if planned:
            completion = metrics.run_duration_s / planned
    result = maths.review(run, points,
                          zone_top=_zone_top(athlete, workout.target_zone if workout else "Z2"),
                          completion=completion, rpe=checkin_rpe(activity))
    return {**base, "available": True, "reason": None, **result}


def build_review(activity: Activity, push: bool = False) -> RunReview | None:
    payload = compute(activity)
    if not payload["available"]:
        return None
    review, created = RunReview.objects.update_or_create(
        activity=activity, defaults={"athlete": activity.athlete, "payload": payload})
    if push and created:
        _push(review)
    return review


def _push(review: RunReview) -> None:
    """R13 "Run reviewed" push (off by default). No numbers in the payload."""
    try:
        from apps.reminders.push import available, send_to_athlete
        from apps.reminders.service import settings_for

        if not available() or not settings_for(review.athlete).run_reviewed:
            return
        ok, _ = send_to_athlete(review.athlete, {
            "title": "Run reviewed", "body": "Your coach review of today's run is ready.",
            "url": f"/activities/{review.activity_id}", "tag": "run_review"})
        if ok:
            review.pushed_at = timezone.now()
            review.save(update_fields=["pushed_at"])
    except Exception:  # noqa: BLE001 — a push failure must not fail the review
        logger.exception("run review push failed for %s", review.pk)


def ai_state(review: RunReview | None) -> dict:
    if review is not None and review.ai_markdown:
        return {"status": "ready", "markdown": review.ai_markdown,
                "generated_at": review.ai_generated_at}
    return {"status": "none", "markdown": "", "generated_at": None}


def review_json(activity: Activity) -> dict:
    review = RunReview.objects.filter(activity=activity).first()
    payload = review.payload if review else compute(activity)
    return {**payload, "ai": ai_state(review), "created_at": review.created_at if review else None}


def recent(athlete) -> dict | None:
    since = timezone.now() - dt.timedelta(hours=RECENT_HOURS)
    review = (RunReview.objects.filter(athlete=athlete, created_at__gte=since)
              .select_related("activity").order_by("-created_at").first())
    if review is None:
        return None
    return {**review.payload, "ai": ai_state(review), "created_at": review.created_at}


REVIEW_USER = """This is a deterministic review of one run, calculated in Python: the run \
against the athlete's similar past runs (same kind of session, same distance band) on \
pace, heart rate at that pace, HR drift, cadence and time spent running, plus the \
went-well / to-improve / next-time bullets.

{payload}

Write 50-100 words of markdown: one encouraging coach paragraph that explains what these \
numbers say and backs the next-time advice. Use only numbers above with their units. \
Describe associations, never causes. Never suggest training harder than the plan."""


def ai_payload(review: RunReview) -> dict:
    p = review.payload
    return {"date": p.get("date"), "kind": p.get("kind"), "bucket": p.get("bucket"),
            "compared_with": p.get("compared_with"), "metrics": p.get("metrics", []),
            "went_well": p.get("went_well", []), "to_improve": p.get("to_improve", []),
            "next_time": p.get("next_time", [])}


def generate_ai(activity: Activity, refresh: bool = False) -> dict:
    """Raises AIUnavailable. Coach tier, cached on the review and by input hash."""
    from apps.coaching.models import AIAnalysis
    from apps.coaching.schemas import ShortParagraph
    from apps.coaching.services import _run

    review = RunReview.objects.filter(activity=activity).first() or build_review(activity)
    if review is None:
        from apps.coaching.client import AIUnavailable

        raise AIUnavailable("Only runs get a coach review.")
    if review.ai_markdown and not refresh:
        return ai_state(review)
    payload = ai_payload(review)
    if refresh:
        from apps.coaching.client import canonical_hash, model_for
        from apps.coaching.prompts import PROMPT_VERSION

        digest = canonical_hash(payload, PROMPT_VERSION, model_for("run_review"))
        AIAnalysis.objects.filter(athlete=activity.athlete, kind=AIAnalysis.Kind.RUN_REVIEW,
                                  input_hash=digest).delete()
    result, _ = _run(activity.athlete, kind=AIAnalysis.Kind.RUN_REVIEW, operation="run_review",
                     payload=payload, activity=activity,
                     user_prompt=REVIEW_USER.format(payload=json.dumps(payload, indent=2,
                                                                       default=str)),
                     schema=ShortParagraph)
    review.ai_markdown = result.markdown
    review.ai_generated_at = timezone.now()
    review.save(update_fields=["ai_markdown", "ai_generated_at"])
    return ai_state(review)
