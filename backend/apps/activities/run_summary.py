"""R15 §C: the "run summary" web push, sized for a watch's notification screen.

Garmin watches mirror phone notifications, so a short title and at most two short body
lines read well on the wrist when Garmin Connect mirrors the browser / installed PWA.
Sent once per run when its post-run review is built; held through the athlete's quiet
hours. Numbers are fine here (the athlete's own device); nothing about habits.
"""

from __future__ import annotations

import datetime as dt
import logging

from django.utils import timezone

logger = logging.getLogger(__name__)

TITLE_MAX = 30
LINE_MAX = 60
RECENT = dt.timedelta(hours=24)
PACE_SAME_S = 3


def fmt_duration(seconds: float | None) -> str:
    s = int(round(seconds or 0))
    h, rest = divmod(s, 3600)
    m, sec = divmod(rest, 60)
    return f"{h}:{m:02d}:{sec:02d}" if h else f"{m}:{sec:02d}"


def fmt_pace(seconds: float | None) -> str:
    s = int(round(seconds or 0))
    return f"{s // 60}:{s % 60:02d}"


def _fit(parts: list[str], limit: int) -> str:
    """Join with " · ", dropping trailing parts until it fits."""
    parts = [p for p in parts if p]
    while parts:
        text = " · ".join(parts)
        if len(text) <= limit:
            return text
        parts = parts[:-1]
    return ""


def compose(*, km: float, moving_s: float, pace_s: float | None, usual_pace_s: float | None,
            hr: int | None, zone_top: int | None, next_title: str | None,
            has_plan: bool) -> dict:
    """Pure: {title, body}. title ≤ 30 chars, body ≤ 2 lines of ≤ 60 chars."""
    title = f"Run {km:.1f} km · {fmt_duration(moving_s)}"
    if len(title) > TITLE_MAX:
        title = f"{km:.1f} km · {fmt_duration(moving_s)}"[:TITLE_MAX]

    pace = None
    if pace_s:
        pace = f"Pace {fmt_pace(pace_s)}"
        if usual_pace_s:
            delta = int(round(pace_s - usual_pace_s))
            if abs(delta) >= PACE_SAME_S:
                word = "faster" if delta < 0 else "slower"
                amount = f"{abs(delta)} s" if abs(delta) < 60 else fmt_pace(abs(delta))
                pace_long = f"{pace} ({amount} {word} than usual)"
            else:
                pace_long = f"{pace} (as usual)"
        else:
            pace_long = pace
    hr_text = None
    if hr:
        hr_text = f"HR {hr}"
        if zone_top:
            hr_long = f"{hr_text} {'on target' if hr <= zone_top else 'above target'}"
        else:
            hr_long = hr_text
    candidates = []
    if pace:
        candidates.append([pace_long, hr_long if hr else None])
        candidates.append([pace, hr_long if hr else None])
        candidates.append([pace, hr_text])
    else:
        candidates.append([hr_long if hr else None])
        candidates.append([hr_text])
    line1 = ""
    for parts in candidates:
        parts = [p for p in parts if p]
        text = " · ".join(parts)
        if len(text) <= LINE_MAX:
            line1 = text
            break
    if not line1 and candidates:
        line1 = _fit(candidates[-1], LINE_MAX)

    line2 = ""
    if has_plan:
        if next_title:
            line2 = f"Next: {next_title}"
            if len(line2) > LINE_MAX:
                line2 = line2[:LINE_MAX - 1].rstrip() + "…"
        else:
            line2 = "Next: rest day"
    body = "\n".join(line for line in (line1, line2) if line)
    return {"title": title, "body": body}


def _facts(activity) -> dict:
    from apps.planning.auto_adjust import _zone_top
    from apps.planning.models import PlannedWorkout, TrainingPlan

    from .models import RunReview

    athlete = activity.athlete
    metrics = getattr(activity, "metrics", None)
    km = (activity.total_distance_m or 0) / 1000
    moving = activity.total_timer_s or activity.total_elapsed_s or 0
    pace = (metrics.run_pace_s_per_km if metrics and metrics.run_pace_s_per_km else
            (moving / km if km > 0.05 else None))
    usual = None
    review = RunReview.objects.filter(activity=activity).first()
    if review:
        row = next((m for m in (review.payload or {}).get("metrics", [])
                    if m.get("key") == "pace"), None)
        usual = row.get("typical") if row else None
    hr = (metrics.avg_run_hr if metrics and metrics.avg_run_hr else activity.avg_hr)
    workout = PlannedWorkout.objects.filter(athlete=athlete, completed_activity=activity).first()
    zone_top = _zone_top(athlete, workout.target_zone) if workout else None
    active = TrainingPlan.objects.filter(athlete=athlete,
                                         status=TrainingPlan.Status.ACTIVE).first()
    next_title, has_plan = None, active is not None
    if active is not None:
        upcoming = (PlannedWorkout.objects.filter(
            athlete=athlete, plan=active, date__gt=activity.local_date,
            status=PlannedWorkout.Status.PLANNED).order_by("date", "id").first())
        tomorrow = activity.local_date + dt.timedelta(days=1)
        if upcoming is not None and upcoming.date == tomorrow:
            next_title = upcoming.title
        elif upcoming is None:
            has_plan = False
    return {"km": km, "moving_s": moving, "pace_s": pace, "usual_pace_s": usual, "hr": hr,
            "zone_top": zone_top, "next_title": next_title, "has_plan": has_plan}


def message(activity) -> dict:
    body = compose(**_facts(activity))
    return {**body, "url": f"/activities/{activity.pk}", "tag": f"run_summary-{activity.pk}",
            "kind": "run_summary"}


def quiet_until(row, local_now: dt.datetime) -> dt.datetime | None:
    """When quiet hours end (aware), or None when it is not quiet now."""
    from apps.reminders.nudges import in_window

    if not in_window(local_now.time().replace(tzinfo=None), row.quiet_start, row.quiet_end):
        return None
    end = dt.datetime.combine(local_now.date(), row.quiet_end, tzinfo=local_now.tzinfo)
    if end <= local_now:
        end = dt.datetime.combine(local_now.date() + dt.timedelta(days=1), row.quiet_end,
                                  tzinfo=local_now.tzinfo)
    return end


def _send(review) -> bool:
    from apps.reminders.push import send_to_athlete

    ok, _ = send_to_athlete(review.athlete, message(review.activity))
    review.summary_due_at = None
    if ok:
        review.pushed_at = timezone.now()
    review.save(update_fields=["summary_due_at", "pushed_at"])
    return bool(ok)


def _eligible(review) -> bool:
    from apps.reminders.push import available
    from apps.reminders.service import settings_for

    if review.pushed_at is not None or not available():
        return False
    if review.activity.started_at < timezone.now() - RECENT:
        return False                      # a backfilled old run: no push
    return settings_for(review.athlete).run_summary


def on_review_built(review) -> str:
    """Called once, when the review is first built. → "sent"|"queued"|"skipped"|"failed"."""
    try:
        if not _eligible(review):
            return "skipped"
        from apps.reminders.service import settings_for

        until = quiet_until(settings_for(review.athlete), review.athlete.local_now)
        if until is not None:
            review.summary_due_at = until
            review.save(update_fields=["summary_due_at"])
            return "queued"
        return "sent" if _send(review) else "failed"
    except Exception:  # noqa: BLE001 — a push failure must not fail the review
        logger.exception("run summary push failed for review %s", review.pk)
        return "failed"


def send_queued() -> int:
    """Beat: send summaries held through quiet hours whose time has come."""
    from apps.reminders.service import settings_for

    from .models import RunReview

    sent = 0
    due = (RunReview.objects.filter(summary_due_at__isnull=False,
                                    summary_due_at__lte=timezone.now(), pushed_at__isnull=True)
           .select_related("activity", "athlete"))
    for review in due:
        try:
            if not _eligible(review):
                review.summary_due_at = None
                review.save(update_fields=["summary_due_at"])
                continue
            until = quiet_until(settings_for(review.athlete), review.athlete.local_now)
            if until is not None:                 # quiet hours were changed meanwhile
                review.summary_due_at = until
                review.save(update_fields=["summary_due_at"])
                continue
            sent += _send(review)
        except Exception:  # noqa: BLE001
            logger.exception("queued run summary failed for review %s", review.pk)
    return sent
